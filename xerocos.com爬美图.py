#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Xerocos.com 图集爬虫 (高质量重构版)

功能:
  - 爬取 xerocos.com 网站的图集。

网站结构 (三级):
  1. Category Pages (`/`, `/?page=N`): 包含多个相册(Album)的入口。
  2. Album Pages (`/view/...`): 单个相册，内部也包含分页 (`?page=N`)。
  3. Image Files: 最终的图片资源。

流程:
  请求分类首页 -> 获取分类总页数 -> 遍历所有分类页 -> 提取相册(标题, 链接)
     └-> (并发处理相册) -> 进入相册首页 -> 获取相册内部总页数
          └-> (并发获取所有分页HTML) -> 解析并收集所有图片链接
               └-> (并发下载图片) -> 下载图片并原子化保存

特点:
  - 高效三级并发:
    1. 并发处理多个不同的相册。
    2. 在相册内部，并发获取其所有子页面的HTML内容。
    3. 收集完所有图片链接后，并发下载图片文件。
  - 健壮的请求与解析:
    - 使用带指数退避的重试机制。
    - 采用更稳定、简洁的CSS选择器，降低因网站更新导致的脚本失效风险。
  - 原子化写入与断点续传: 保证文件完整性，支持任务中断后继续。
  - 内存高效: 采用“边发现边处理”的流式处理模式。
  - 高度可配置与可维护: 代码结构清晰，职责分离，易于理解和扩展。
"""
import os
import re
import time
import random
import argparse
import logging
from urllib.parse import urljoin, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Optional, Set

import requests
from bs4 import BeautifulSoup

# -------- 默认配置 --------
BASE_URL = "https://xerocos.com"
DEFAULT_SAVE_DIR = "美女图集"
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 20
DEFAULT_CONCURRENCY_ALBUM = 4       # 并发处理相册数量
DEFAULT_CONCURRENCY_PAGE = 4        # 每个相册内部并发获取分页HTML的数量
DEFAULT_CONCURRENCY_IMAGE = 8       # 每个相册内部并发下载图片数量
DEFAULT_PAGE_SLEEP = 2.0            # 爬取每个分类页后的延迟
DEFAULT_IMAGE_SLEEP = 0.5           # 每张图片下载成功后的短暂延迟

# -------- 跳过已知问题的URL --------
SKIP_URLS = {
    "https://xerocos.com/view/aqua-kiara-sessyoin",
}

# -------- 日志设置 --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# -------- 辅助函数 (高质量代码模板) --------
def make_session() -> requests.Session:
    """创建并配置requests.Session。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": BASE_URL
    })
    return s

def request_text(session: requests.Session, url: str, retries: int, timeout: int) -> Optional[str]:
    """请求文本页面，带重试和指数退避。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
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
    name = unquote(name)
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
def parse_max_page_number(soup: BeautifulSoup) -> int:
    """从分页导航中稳健地解析出最大页码。"""
    page_numbers = {1}
    # 查找所有可能是页码的链接
    for link in soup.select('a[href*="?page="]'):
        # 尝试从链接文本中提取
        text = link.get_text(strip=True)
        if text.isdigit():
            page_numbers.add(int(text))
        # 尝试从href属性中提取
        match = re.search(r'\?page=(\d+)', link.get('href', ''))
        if match:
            page_numbers.add(int(match.group(1)))
    return max(page_numbers)

def parse_albums_on_category_page(html: str) -> List[Tuple[str, str]]:
    """从分类页HTML中解析出(相册标题, 相册URL)元组列表。"""
    soup = BeautifulSoup(html, "html.parser")
    albums = []
    # 使用更稳定、简洁的选择器定位到每个相册的卡片
    for card in soup.select("div.latest-card"):
        a_tag = card.find("a", href=True)
        img_tag = card.find("img", alt=True)
        if a_tag and img_tag:
            url = urljoin(BASE_URL, a_tag['href'])
            title = sanitize_filename(img_tag['alt'])
            albums.append((title, url))
    return albums

def parse_images_on_album_page(html: str) -> Set[str]:
    """从相册的单个分页HTML中解析出所有图片的绝对URL集合。"""
    soup = BeautifulSoup(html, "html.parser")
    image_urls = set()
    # 定位到图片容器，然后提取所有懒加载的图片
    for img in soup.select("div.justify-center img[data-src]"):
        src = img.get("data-src")
        if src:
            image_urls.add(urljoin(BASE_URL, src))
    return image_urls

# -------- 下载核心逻辑 --------
def download_single_image(session: requests.Session, url: str, album_dir: str, args: argparse.Namespace) -> str:
    """下载单张图片，返回状态字符串。"""
    filename = sanitize_filename(os.path.basename(unquote(url)))
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

# -------- 相册处理主流程 --------
def process_album(session: requests.Session, title: str, url: str, save_root: str, args: argparse.Namespace) -> Dict[str, int]:
    """处理单个相册：并发获取所有分页内容，再并发下载所有图片。"""
    logging.info("开始处理相册: %s", title)
    
    first_page_html = request_text(session, url, retries=args.retries, timeout=args.timeout)
    if not first_page_html:
        logging.error("无法获取相册首页: %s", url)
        return {"ok": 0, "skipped": 0, "fail": 1}

    total_album_pages = parse_max_page_number(BeautifulSoup(first_page_html, "html.parser"))
    logging.info("相册 '%s' 共 %d 页", title, total_album_pages)

    # 1. 高效收集所有图片URL
    all_image_urls = parse_images_on_album_page(first_page_html)
    
    page_urls_to_fetch = [f"{url}?page={p}" for p in range(2, total_album_pages + 1)]
    
    with ThreadPoolExecutor(max_workers=args.page_concurrency, thread_name_prefix='PageFetcher') as executor:
        future_to_html = {executor.submit(request_text, session, page_url, args.retries, args.timeout): page_url for page_url in page_urls_to_fetch}
        for future in as_completed(future_to_html):
            page_html = future.result()
            if page_html:
                all_image_urls.update(parse_images_on_album_page(page_html))

    if not all_image_urls:
        logging.warning("在相册 '%s' 中未解析到任何图片", title)
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
    
    logging.info("相册 '%s' 处理完成. 结果: %s", title, results)
    return results

# -------- 主函数 --------
def main():
    parser = argparse.ArgumentParser(description="Xerocos.com 图集爬虫 (高质量重构版)", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="图片保存的根目录")
    parser.add_argument("--start", type=int, default=1, help="起始分类页码")
    parser.add_argument("--end", type=int, default=0, help="结束分类页码 (0 代表自动检测)")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求失败最大重试次数")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时时间(秒)")
    parser.add_argument("-c", "--album-concurrency", type=int, default=DEFAULT_CONCURRENCY_ALBUM, help="并发处理的相册数量")
    parser.add_argument("-p", "--page-concurrency", type=int, default=DEFAULT_CONCURRENCY_PAGE, help="相册内部并发获取分页数")
    parser.add_argument("-w", "--image-concurrency", type=int, default=DEFAULT_CONCURRENCY_IMAGE, help="相册内部并发下载图片数")
    parser.add_argument("--page-sleep", type=float, default=DEFAULT_PAGE_SLEEP, help="爬取每个分类页后的延迟(秒)")
    parser.add_argument("--image-sleep", type=float, default=DEFAULT_IMAGE_SLEEP, help="每张图片下载成功后的延迟(秒)")
    args = parser.parse_args()

    session = make_session()
    save_root = os.path.abspath(args.dir)
    os.makedirs(save_root, exist_ok=True)
    
    logging.info("请求分类首页以获取总页数...")
    home_html = request_text(session, BASE_URL, args.retries, args.timeout)
    if not home_html:
        logging.critical("无法获取网站首页，程序退出。")
        return

    total_category_pages = parse_max_page_number(BeautifulSoup(home_html, "html.parser"))
    logging.info("检测到分类总页数: %d", total_category_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end > 0 and args.end >= start_page else total_category_pages
    
    summary = {"ok": 0, "skipped": 0, "fail": 0, "albums_processed": 0}
    seen_album_urls: Set[str] = set()
    
    with ThreadPoolExecutor(max_workers=args.album_concurrency, thread_name_prefix='AlbumProcessor') as executor:
        future_map = {}
        for page_num in range(start_page, end_page + 1):
            page_url = f"{BASE_URL}/?page={page_num}" if page_num > 1 else BASE_URL
            logging.info("开始处理分类页 %d/%d -> %s", page_num, end_page, page_url)
            
            list_html = request_text(session, page_url, args.retries, args.timeout)
            if not list_html: continue

            for title, url in parse_albums_on_category_page(list_html):
                if url in SKIP_URLS:
                    logging.info("根据配置跳过: %s", url)
                    continue
                if url not in seen_album_urls:
                    seen_album_urls.add(url)
                    future = executor.submit(process_album, session, title, url, save_root, args)
                    future_map[future] = (title, url)
            time.sleep(args.page_sleep + random.random())

        logging.info("所有分类页遍历完毕，等待 %d 个相册任务完成...", len(future_map))
        for future in as_completed(future_map):
            title, url = future_map[future]
            try:
                result = future.result()
                summary.update({k: summary.get(k, 0) + v for k, v in result.items()})
                if any(result.values()):
                    summary["albums_processed"] += 1
            except Exception:
                logging.exception("处理相册 '%s' 时发生未捕获的异常: %s", title, url)
    
    logging.info("=" * 50)
    logging.info("所有任务完成！")
    logging.info(
        "处理相册数: %d, 成功下载: %d, 跳过: %d, 失败: %d",
        summary["albums_processed"], summary["ok"], summary["skipped"], summary["fail"]
    )
    logging.info("=" * 50)

if __name__ == "__main__":
    main()
