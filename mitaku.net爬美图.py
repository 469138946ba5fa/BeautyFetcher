#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
美女图集爬虫
请求首页 -> 获取总页数
   └→ 循环请求每页列表 -> 提取专辑条目和链接
          └→ 循环请求每个专辑链接 -> 提取图片数和图片链接
                 └→ 循环下载图片
流程：
mitaku.net 爬虫（下载 images/ 下的专辑图片）
主页 → 分页 → 专辑 → 子分页 → 详情页 → 图片
  首页 -> 获取总页数（div.wp-pagenavi span.pages "Page 1 of N"） ->
  遍历分页（/page/X/）-> 提取每页 article 中的专辑链接 ->
  进入专辑页提取图片链接（优先抓取 /wp-content/uploads/ 的 img） ->
  多线程下载到 images/<专辑名>/

特点：
  - 请求重试机制
  - 并发处理（专辑并发 + 专辑内并发下载）
  - 已存在文件跳过（断点续传）
  - 日志与参数化
mitaku.net 完整爬虫（按要求：详情页取第一张图 + 图片总数 -> 拼接 -> 下载）
保存到 images/<postid - sanitized_title>/ 下，支持并发、重试、断点续传。
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
    "https://mitaku.net",
    # 可以添加其他可能的镜像站
]
DEFAULT_SAVE_DIR = "美女图集"
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 15
DEFAULT_CONCURRENCY_ALBUM = 6       # 并发处理相册数量
DEFAULT_CONCURRENCY_IMAGE = 6       # 每个相册内部并发下载图片数量
DEFAULT_PAGE_SLEEP = 1.0            # 爬取每个列表页后的延迟
DEFAULT_IMAGE_SLEEP = 0.4           # 每张图片下载成功后的短暂延迟

# -------- 日志设置 --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# -------- 辅助函数 (高质量代码模板) --------
def find_active_base_url(session: requests.Session, urls: List[str], timeout: int) -> Optional[str]:
    """测试URL列表，返回第一个可用的URL。"""
    for url in urls:
        try:
            logging.info("正在测试域名: %s", url)
            response = session.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code < 400:
                logging.info("域名 %s 可用", response.url)
                return response.url.rstrip('/')
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

def sanitize_filename(name: str, maxlen: int = 120) -> str:
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

# -------- 解析函数 (已加入类型注解) --------
def parse_total_pages(html: str) -> int:
    """从首页HTML中稳健地解析出总页数。"""
    soup = BeautifulSoup(html, "html.parser")
    # 策略1: 'Page 1 of N'
    span = soup.select_one("div.wp-pagenavi span.pages")
    if span:
        match = re.search(r'of\s+(\d+)', span.get_text(), re.I)
        if match:
            return int(match.group(1))
    # 策略2: 最后一个页码链接 `a.last`
    a_last = soup.select_one("div.wp-pagenavi a.last[href]")
    if a_last:
        match = re.search(r'/page/(\d+)/', a_last["href"])
        if match:
            return int(match.group(1))
    # 策略3: 所有页码链接中的最大值
    page_numbers = {1}
    for a in soup.select("div.wp-pagenavi a[href]"):
        match = re.search(r'/page/(\d+)/', a["href"])
        if match:
            page_numbers.add(int(match.group(1)))
    return max(page_numbers)

def parse_albums_on_page(html: str, base_url: str) -> List[Tuple[str, str]]:
    """从列表页HTML中解析出(标题, URL)元组列表。"""
    soup = BeautifulSoup(html, "html.parser")
    albums = []
    for art in soup.select("article"):
        a_tag = art.select_one(".featured-image a[href]") or art.select_one("h2.entry-title a[href]")
        if a_tag:
            href = a_tag.get("href", "").strip()
            title = a_tag.get("title") or a_tag.get_text(strip=True) or ""
            if href:
                albums.append((title.strip(), urljoin(base_url, href)))
    return albums

def parse_album_details(html: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """从相册详情页解析：post_id, 标题, 首图URL, 图片总数。"""
    soup = BeautifulSoup(html, "html.parser")
    post_id, title, first_img_url, total = None, None, None, None
    # Post ID
    art = soup.find("article", id=re.compile(r'post-\d+'))
    if art: post_id = art["id"].replace('post-', '')
    # Title
    title_tag = soup.select_one("h1.entry-title")
    if title_tag: title = title_tag.get_text(strip=True)
    # First Image URL
    a_tag = soup.select_one("a.msacwl-img-link[data-mfp-src], a[data-mfp-src]")
    if a_tag:
        first_img_url = a_tag.get("data-mfp-src", "").split("?")[0]
    else:
        img_tag = soup.select_one("div.msacwl-img-wrap img[src], article img[src]")
        if img_tag: first_img_url = img_tag.get("src", "").split("?")[0]
    # Total Images
    text_match = soup.find(string=re.compile(r"Image\s*:\s*\d+\s*Pics", re.I))
    if text_match:
        match = re.search(r"Image\s*:\s*(\d+)", text_match, re.I)
        if match: total = int(match.group(1))
    return post_id, title, first_img_url, total

def build_image_list_from_pattern(first_url: str, total: int) -> List[str]:
    """根据首图URL和总数，通过模式匹配生成图片URL列表。"""
    match = re.match(r'(.+?)-(\d+)(\.[A-Za-z0-9]+)$', first_url)
    if not match: return []
    prefix, _, suffix = match.groups()
    return [f"{prefix}-{i}{suffix}" for i in range(1, total + 1)]

def fallback_parse_images(html: str) -> List[str]:
    """备用方法：直接从页面中提取所有可能是图片链接的URL。"""
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.select("a[data-mfp-src]"):
        urls.add(a["data-mfp-src"].split("?")[0])
    for img in soup.select("img[src]"):
        if "/wp-content/uploads/" in img["src"]:
             urls.add(img["src"].split("?")[0])
    
    sorted_urls = sorted(list(urls), key=lambda u: int(re.search(r'-(\d+)\.[a-z]+$', u).group(1)) if re.search(r'-(\d+)\.[a-z]+$', u) else 0)
    return sorted_urls

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

# -------- 相册处理主流程 --------
def process_album(session: requests.Session, title: str, url: str, save_root: str, base_url: str, args: argparse.Namespace) -> Dict[str, int]:
    """处理单个相册：获取详情 -> 生成链接列表 -> 并发下载。"""
    logging.info("开始处理相册: %s", title)
    
    html = request_text(session, url, retries=args.retries, timeout=args.timeout)
    if not html:
        logging.error("无法获取相册页面: %s", url)
        return {"ok": 0, "skipped": 0, "fail": 1}

    post_id, real_title, first_img, total = parse_album_details(html)
    folder_name = f"{post_id} - {sanitize_filename(real_title or title)}" if post_id else sanitize_filename(real_title or title)
    album_dir = os.path.join(save_root, folder_name)

    img_urls = []
    if first_img and total:
        img_urls = build_image_list_from_pattern(first_img, total)
        if not img_urls:
            logging.warning("首图URL模式不匹配，回退到页面抓取: %s", url)
            img_urls = fallback_parse_images(html)
    else:
        logging.warning("未找到总数或首图，回退到页面抓取: %s", url)
        img_urls = fallback_parse_images(html)

    if not img_urls:
        logging.warning("在相册 '%s' 中未解析到任何图片", title)
        return {"ok": 0, "skipped": 0, "fail": 0}

    # 确保所有URL都是绝对路径
    final_urls = {urljoin(base_url, u) for u in img_urls}
    
    os.makedirs(album_dir, exist_ok=True)
    logging.info("准备为 '%s' 下载 %d 张图片...", title, len(final_urls))
    
    results: Dict[str, int] = {"ok": 0, "skipped": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=args.image_concurrency, thread_name_prefix='ImageDownloader') as executor:
        future_map = {executor.submit(download_single_image, session, img_url, album_dir, args): img_url for img_url in final_urls}
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
    parser = argparse.ArgumentParser(description="Mitaku.net 图集爬虫 (专业级重构版)", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="图片保存的根目录")
    parser.add_argument("--start", type=int, default=1, help="起始列表页码")
    parser.add_argument("--end", type=int, default=0, help="结束列表页码 (0 代表自动检测)")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求失败最大重试次数")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时时间(秒)")
    parser.add_argument("-c", "--album-concurrency", type=int, default=DEFAULT_CONCURRENCY_ALBUM, help="并发处理的相册数量")
    parser.add_argument("-w", "--image-concurrency", type=int, default=DEFAULT_CONCURRENCY_IMAGE, help="相册内部并发下载图片数")
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
    
    home_html = request_text(session, base_url, args.retries, args.timeout)
    if not home_html:
        logging.critical("无法获取网站首页，程序退出。")
        return

    total_site_pages = parse_total_pages(home_html)
    logging.info("检测到网站总页数: %d", total_site_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end > 0 and args.end >= start_page else total_site_pages
    
    summary: Dict[str, int] = {"ok": 0, "skipped": 0, "fail": 0, "albums_processed": 0}
    seen_album_urls: Set[str] = set()
    
    with ThreadPoolExecutor(max_workers=args.album_concurrency, thread_name_prefix='AlbumProcessor') as executor:
        future_map = {}
        for page_num in range(start_page, end_page + 1):
            page_url = f"{base_url}/page/{page_num}/" if page_num > 1 else base_url
            logging.info("开始处理列表页 %d/%d -> %s", page_num, end_page, page_url)
            
            list_html = request_text(session, page_url, args.retries, args.timeout)
            if not list_html: continue

            for title, url in parse_albums_on_page(list_html, base_url):
                if url not in seen_album_urls:
                    seen_album_urls.add(url)
                    future = executor.submit(process_album, session, title, url, save_root, base_url, args)
                    future_map[future] = (title, url)
            time.sleep(args.page_sleep + random.random())

        logging.info("所有列表页遍历完毕，等待 %d 个相册任务完成...", len(future_map))
        for future in as_completed(future_map):
            title, url = future_map[future]
            try:
                result = future.result()
                summary.update({k: summary.get(k, 0) + v for k, v in result.items()})
                if any(v > 0 for k, v in result.items() if k != "skipped"):
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
