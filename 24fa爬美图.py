#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
24FA/OK/II/ME/FAA.cc 系列网站图集爬虫 (高质量重构版)

功能:
  - 爬取指定分类下的所有图集。

网站结构:
  - 域名可能频繁更换，内置多个备用域名。
  - 分类页(c49.aspx) -> 列表分页(c49p2.aspx...) -> 专辑页(n...aspx)
  - 专辑页内部也有分页(n...p2.aspx...)
  - 图片URL格式为 .../123.jpg_gzip.aspx

流程:
  自动寻找可用域名 -> 请求分类首页 -> 获取列表总页数
     └-> 遍历列表页 -> 提取专辑(标题, 链接)
          └-> (并发处理专辑) -> 进入专辑页 -> 获取内部总页数
               └-> (并发获取所有分页HTML) -> 解析收集所有图片链接
                    └-> (并发下载图片) -> 清洗文件名并保存

特点:
  - 域名自动切换: 启动时自动检测可用的BASE_URL，提高抗失效能力。
  - 高效三级并发:
    1. 并发处理多个专辑。
    2. 在专辑内部，并发获取所有分页的HTML。
    3. 收集完链接后，并发下载所有图片。
  - 健壮的解析与请求: 采用更可靠的CSS选择器和带指数退避的重试策略。
  - 原子化写入/断点续传: 保证文件安全，支持任务中断后继续。
  - 内存高效: 采用“边发现边处理”模式，无需一次性加载所有专辑信息。
  - 高度可配置与可维护: 代码结构清晰，参数灵活，注释详尽。
"""
import os
import re
import time
import random
import argparse
import logging
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Optional, Set

import requests
from bs4 import BeautifulSoup

# -------- 默认配置 --------
# 备用域名列表，程序将自动选择一个可用的
BASE_URLS = [
    "https://www.24faa.cc/",
    "https://www.24me.cc/",
    "https://www.24ii.cc/",
    "https://www.24ok.cc/",
    "https://www.24fa.com/",
]
ALBUM_CATEGORY_PATH = "c49.aspx"  # 目标分类路径
DEFAULT_SAVE_DIR = "美女图集"
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 20
DEFAULT_CONCURRENCY_ALBUM = 5      # 并发处理专辑数量
DEFAULT_CONCURRENCY_PAGE = 4       # 每个专辑内部并发获取分页HTML的数量
DEFAULT_CONCURRENCY_IMAGE = 8      # 每个专辑内部并发下载图片数量
DEFAULT_PAGE_SLEEP = 2.0           # 爬取每个列表页后的延迟
DEFAULT_IMAGE_SLEEP = 0.5          # 每张图片下载成功后的短暂延迟

# -------- 日志设置 --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# -------- 辅助函数 (高质量代码模板) --------
def find_active_base_url(session: requests.Session, urls: List[str], timeout: int) -> Optional[str]:
    """测试URL列表，返回第一个可用的URL。"""
    for url in urls:
        try:
            logging.info("正在测试域名: %s", url)
            response = session.head(url, timeout=timeout)
            if response.status_code < 400:
                logging.info("域名 %s 可用", url)
                return url
        except requests.RequestException:
            logging.warning("域名 %s 测试失败", url)
    return None

def make_session() -> requests.Session:
    """创建并配置requests.Session。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    })
    return s

def request_text(session: requests.Session, url: str, retries: int, timeout: int) -> Optional[str]:
    """请求文本页面，带重试和指数退避。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            # 网站可能会返回一个JS重定向页面，简单检查一下
            if "window.location.href" in r.text and "goback" in r.text:
                 logging.warning("检测到JS重定向或错误页面: %s", url)
                 return None
            return r.text
        except requests.RequestException as e:
            logging.warning("请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.3) + random.random())
    return None

def request_binary(session: requests.Session, url: str, retries: int, timeout: int) -> Optional[bytes]:
    """请求二进制文件(图片)，带重试和指数退避。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            logging.warning("图片请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.25) + random.random())
    return None

def sanitize_filename(name: str, maxlen: int = 150) -> str:
    """清洗并截断文件名/文件夹名。"""
    if not name: return "untitled"
    # 特殊处理该网站的文件名后缀
    name = unquote(name).replace(".jpg_gzip.aspx", ".jpg")
    s = re.sub(r'[\0\/\\:\*\?\"<>\|]+', "_", name).strip()
    return s[:maxlen] or "untitled"

def save_bytes_atomic(path: str, data: bytes) -> bool:
    """原子化写入文件，避免文件损坏。"""
    tmp_path = path + ".part"
    try:
        with open(tmp_path, "wb") as f: f.write(data)
        os.replace(tmp_path, path)
        return True
    except IOError as e:
        logging.error("文件写入失败 %s : %s", path, e)
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        return False

# -------- 解析函数 --------
def parse_total_pages(soup: BeautifulSoup) -> int:
    """从分页导航(div.pager)中稳健地解析出最大页码。"""
    pager_div = soup.find("div", class_="pager")
    if not pager_div: return 1
    
    page_numbers = {1}
    for li in pager_div.find_all("li"):
        text = li.get_text(strip=True)
        if text.isdigit():
            page_numbers.add(int(text))
    return max(page_numbers)

def parse_albums_on_listing_page(html: str, base_url: str) -> List[Tuple[str, str]]:
    """从列表页HTML中解析出(标题, URL)元组列表。"""
    soup = BeautifulSoup(html, "html.parser")
    albums = []
    # 采用更稳健的解析方式，遍历每个专辑的容器
    for item in soup.select("div.mx > ul > li"):
        a_tag = item.find("a", href=True)
        h5_tag = item.find("h5")
        if a_tag and h5_tag and a_tag['href'].startswith('n') and a_tag['href'].endswith('.aspx'):
            title = sanitize_filename(h5_tag.get_text(strip=True))
            url = urljoin(base_url, a_tag['href'])
            albums.append((title, url))
    return albums

def parse_images_on_album_page(html: str, base_url: str) -> Set[str]:
    """从专辑的单个分页HTML中解析出所有图片的绝对URL集合。"""
    soup = BeautifulSoup(html, "html.parser")
    image_urls = set()
    content_div = soup.find("div", id="content")
    if content_div:
        for img in content_div.find_all("img", src=True):
            src = img['src']
            if src.startswith("upload/") and src.endswith(".jpg_gzip.aspx"):
                image_urls.add(urljoin(base_url, src))
    return image_urls

# -------- 下载核心逻辑 --------
def download_single_image(session: requests.Session, url: str, album_dir: str, args: argparse.Namespace) -> str:
    """下载单张图片，返回状态字符串。"""
    filename = sanitize_filename(os.path.basename(urlparse(url).path))
    dest_path = os.path.join(album_dir, filename)

    if os.path.exists(dest_path):
        return "skipped"

    data = request_binary(session, url, retries=args.retries, timeout=args.timeout)
    if data:
        if save_bytes_atomic(dest_path, data):
            logging.info("下载成功: %s", dest_path)
            time.sleep(args.image_sleep + random.random() * 0.5)
            return "ok"
    return "fail"

# -------- 专辑处理主流程 --------
def process_album(session: requests.Session, title: str, url: str, save_root: str, base_url: str, args: argparse.Namespace) -> Dict[str, int]:
    """处理单个专辑：并发获取所有分页内容，再并发下载所有图片。"""
    logging.info("开始处理专辑: %s", title)
    
    first_page_html = request_text(session, url, retries=args.retries, timeout=args.timeout)
    if not first_page_html:
        logging.error("无法获取专辑首页: %s", url)
        return {"ok": 0, "skipped": 0, "fail": 1}

    total_album_pages = parse_total_pages(BeautifulSoup(first_page_html, "html.parser"))
    logging.info("专辑 '%s' 共 %d 页", title, total_album_pages)

    # 1. 高效收集所有图片URL
    all_image_urls = parse_images_on_album_page(first_page_html, base_url)
    
    # 并发获取第2页及之后的所有分页HTML
    page_urls_to_fetch = [url.rsplit(".", 1)[0] + f"p{p}.aspx" for p in range(2, total_album_pages + 1)]
    
    with ThreadPoolExecutor(max_workers=args.page_concurrency, thread_name_prefix='PageFetcher') as executor:
        future_to_url = {executor.submit(request_text, session, page_url, args.retries, args.timeout): page_url for page_url in page_urls_to_fetch}
        for future in as_completed(future_to_url):
            page_html = future.result()
            if page_html:
                all_image_urls.update(parse_images_on_album_page(page_html, base_url))

    if not all_image_urls:
        logging.warning("在专辑 '%s' 中未解析到任何图片", title)
        return {"ok": 0, "skipped": 0, "fail": 0}

    # 2. 并发下载所有图片
    album_dir = os.path.join(save_root, title)
    os.makedirs(album_dir, exist_ok=True)
    logging.info("准备为 '%s' 下载 %d 张图片...", title, len(all_image_urls))
    
    results = {"ok": 0, "skipped": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=args.image_concurrency, thread_name_prefix='ImageDownloader') as executor:
        future_map = {executor.submit(download_single_image, session, img_url, album_dir, args): img_url for img_url in all_image_urls}
        for future in as_completed(future_map):
            try:
                status = future.result()
                results[status] += 1
            except Exception:
                img_url = future_map[future]
                logging.exception("图片下载任务异常 [%s]", img_url)
                results["fail"] += 1
    
    logging.info("专辑 '%s' 处理完成. 结果: %s", title, results)
    return results

# -------- 主函数 --------
def main():
    parser = argparse.ArgumentParser(description="24FA系列网站图集爬虫 (高质量重构版)", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="图片保存的根目录")
    parser.add_argument("--start", type=int, default=1, help="起始列表页码")
    parser.add_argument("--end", type=int, default=0, help="结束列表页码 (0 代表自动检测)")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求失败最大重试次数")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时时间(秒)")
    parser.add_argument("-c", "--album-concurrency", type=int, default=DEFAULT_CONCURRENCY_ALBUM, help="并发处理的专辑数量")
    parser.add_argument("-p", "--page-concurrency", type=int, default=DEFAULT_CONCURRENCY_PAGE, help="专辑内部并发获取分页数")
    parser.add_argument("-w", "--image-concurrency", type=int, default=DEFAULT_CONCURRENCY_IMAGE, help="专辑内部并发下载图片数")
    parser.add_argument("--page-sleep", type=float, default=DEFAULT_PAGE_SLEEP, help="爬取每个列表页后的延迟(秒)")
    parser.add_argument("--image-sleep", type=float, default=DEFAULT_IMAGE_SLEEP, help="每张图片下载成功后的延迟(秒)")
    args = parser.parse_args()

    session = make_session()
    base_url = find_active_base_url(session, BASE_URLS, args.timeout)
    if not base_url:
        logging.critical("所有备用域名都无法访问，程序退出。")
        return
        
    save_root = os.path.abspath(args.dir)
    os.makedirs(save_root, exist_ok=True)
    
    main_list_url = urljoin(base_url, ALBUM_CATEGORY_PATH)
    logging.info("请求分类首页: %s", main_list_url)
    home_html = request_text(session, main_list_url, retries=args.retries, timeout=args.timeout)
    if not home_html:
        logging.critical("无法获取分类首页，程序退出。")
        return

    total_site_pages = parse_total_pages(BeautifulSoup(home_html, "html.parser"))
    logging.info("检测到列表总页数: %d", total_site_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end > 0 and args.end >= start_page else total_site_pages
    
    summary = {"ok": 0, "skipped": 0, "fail": 0, "albums_processed": 0}
    seen_album_urls: Set[str] = set()
    
    with ThreadPoolExecutor(max_workers=args.album_concurrency, thread_name_prefix='AlbumProcessor') as executor:
        future_map = {}
        for page_num in range(start_page, end_page + 1):
            page_url = main_list_url if page_num == 1 else main_list_url.rsplit(".", 1)[0] + f"p{page_num}.aspx"
            logging.info("开始处理列表页 %d/%d -> %s", page_num, end_page, page_url)
            
            list_html = request_text(session, page_url, args.retries, args.timeout)
            if not list_html: continue

            for title, url in parse_albums_on_listing_page(list_html, base_url):
                if url not in seen_album_urls:
                    seen_album_urls.add(url)
                    future = executor.submit(process_album, session, title, url, save_root, base_url, args)
                    future_map[future] = (title, url)
            time.sleep(args.page_sleep + random.random())

        logging.info("所有列表页遍历完毕，等待 %d 个专辑任务完成...", len(future_map))
        for future in as_completed(future_map):
            title, url = future_map[future]
            try:
                result = future.result()
                summary["ok"] += result.get("ok", 0)
                summary["skipped"] += result.get("skipped", 0)
                summary["fail"] += result.get("fail", 0)
                summary["albums_processed"] += 1
            except Exception:
                logging.exception("处理专辑 '%s' 时发生未捕获的异常: %s", title, url)
    
    logging.info("=" * 50)
    logging.info("所有任务完成！")
    logging.info(
        "处理专辑数: %d, 成功下载: %d, 跳过: %d, 失败: %d",
        summary["albums_processed"], summary["ok"], summary["skipped"], summary["fail"]
    )
    logging.info("=" * 50)

if __name__ == "__main__":
    main()
