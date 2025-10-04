#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Meiru.neocities.org 图集爬虫 (高质量重构版)

功能:
  - 爬取 meiru.neocities.org 网站的图片集。

网站结构:
  - 主站分页 -> 列表页 -> 专辑链接
  - 专辑页内部也存在分页
  - 图片从第三方图床下载

流程:
  主页 -> 获取主站总页数 -> 遍历所有列表页 -> 提取专辑链接
     └-> (并发处理专辑) -> 进入专辑页 -> 获取专辑标题和内部总页数
          └-> 遍历专辑内所有分页 -> 收集所有图片文件名
               └-> (并发下载图片) -> 尝试从多个图床下载并保存

特点:
  - 两级并发: 并发处理多个专辑，并在每个专辑内部并发下载所有图片。
  - 健壮的请求与重试: 使用指数退避和随机抖动策略，有效应对网络问题。
  - 原子化写入: 安全地保存文件，避免因意外中断产生损坏的图片。
  - 断点续传: 自动跳过已完整下载的文件。
  - 内存高效: 边发现专辑边处理，无需将所有链接存入内存。
  - 多图床支持: 自动轮询多个备用图片CDN，提高下载成功率。
  - 可配置与可维护: 代码结构清晰，参数灵活，易于理解和修改。
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
BASE_URL = "https://meiru.neocities.org"
# 可靠的图片CDN列表，程序会自动按顺序尝试
TG_URLS = [
    "https://teleimgs.netlib.re/file",
    "https://telegraph-image.pages.dev/file",
    "https://im.gurl.eu.org/file"
]
DEFAULT_SAVE_DIR = "美女图集"
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 20
DEFAULT_CONCURRENCY_ALBUM = 4       # 并发处理专辑数量
DEFAULT_CONCURRENCY_IMAGE = 8       # 每个专辑内部并发下载图片数量
DEFAULT_PAGE_SLEEP = 1.0            # 爬取每个列表页后的延迟
DEFAULT_IMAGE_SLEEP = 0.2           # 每张图片下载成功后的短暂延迟

# -------- 跳过已知问题的URL --------
SKIP_URLS = {
    "https://meiru.neocities.org/view/aqua-kiara-sessyoin",
}

# -------- 日志设置 --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# -------- 辅助函数 (高质量代码模板) --------
def make_session() -> requests.Session:
    """创建一个配置好 User-Agent 的 requests.Session 对象"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": BASE_URL
    })
    return s

def request_text(session: requests.Session, url: str, retries: int = DEFAULT_RETRIES, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """请求文本页面，带重试和指数退避，并保证正确解码。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()  # 遇到 4xx/5xx 错误时会抛出异常
            # 自动识别编码，优先用网页自带声明，其次 fallback 到 UTF-8
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException as e:
            logging.warning("请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.3) + random.random())
    return None

def request_binary(session: requests.Session, url: str, retries: int = DEFAULT_RETRIES, timeout: int = DEFAULT_TIMEOUT) -> Optional[bytes]:
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
    """清洗并截断文件名，避免乱码或非法字符。"""
    if not name:
        return "untitled"
    # 去掉前后空格
    name = name.strip()
    # 替换掉不允许的字符
    s = re.sub(r'[\0\/\\:\*\?\"<>\|]+', "_", name)
    # 限制长度，防止路径过长
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
    """从分页导航(div#pagination)中解析出最大页码。"""
    page_numbers = {1}
    for link in soup.select("div#pagination a[href]"):
        text = link.get_text(strip=True)
        if text.isdigit():
            page_numbers.add(int(text))
        else:
            match = re.search(r'[=/](\d+)', link.get('href', ''))
            if match:
                page_numbers.add(int(match.group(1)))
    return max(page_numbers)

def parse_albums_on_listing_page(html: str) -> List[str]:
    """从主站的列表页HTML中解析出所有专辑的URL。"""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select('div.text-center.font-semibold a[href]')
    return [urljoin(BASE_URL, link['href']) for link in links]

def parse_album_info(html: str) -> Tuple[str, int]:
    """从专辑首页HTML中解析出专辑标题和内部总页数。"""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("h1")
    title = sanitize_filename(title_tag.get_text(strip=True)) if title_tag else "未命名专辑"
    total_pages = parse_max_page_number(soup)
    return title, total_pages

def parse_images_on_album_page(html: str) -> List[str]:
    """从专辑的单个分页HTML中解析出所有图片的原始文件名。"""
    soup = BeautifulSoup(html, "html.parser")
    filenames = []
    gallery_div = soup.find("div", id="gallery")
    if gallery_div:
        for img in gallery_div.select("img.block.my-2.mx-auto[src]"):
            src = img.get("src", "")
            # 文件名规则：.jpg -> .png
            filename = os.path.basename(src).replace(".jpg", ".png")
            if filename:
                filenames.append(filename)
    return filenames

# -------- 下载核心逻辑 --------
def download_single_image(session: requests.Session, filename: str, album_dir: str, args: argparse.Namespace) -> str:
    """下载单张图片，包含检查存在、多源重试、原子写入的逻辑。返回状态。"""
    dest_path = os.path.join(album_dir, sanitize_filename(filename))
    if os.path.exists(dest_path):
        return "skipped"

    img_content = None
    for tg_url_base in TG_URLS:
        img_url = f"{tg_url_base}/{filename}"
        img_content = request_binary(session, img_url, retries=2, timeout=args.timeout)
        if img_content:
            break
    
    if not img_content:
        logging.warning("下载失败 (已尝试所有图床): %s", filename)
        return "fail"
        
    if save_bytes_atomic(dest_path, img_content):
        logging.info("下载成功: %s", dest_path)
        time.sleep(args.image_sleep + random.random() * 0.2)
        return "ok"
    else:
        return "fail"

# -------- 专辑处理主流程 --------
def process_album(session: requests.Session, album_url: str, save_root: str, args: argparse.Namespace) -> Dict[str, int]:
    """处理单个专辑的完整流程：获取所有图片链接 -> 并发下载。"""
    logging.info("开始处理专辑: %s", album_url)
    
    # 1. 获取专辑首页信息
    first_page_html = request_text(session, album_url, retries=args.retries, timeout=args.timeout)
    if not first_page_html:
        logging.error("无法获取专辑首页: %s", album_url)
        return {"ok": 0, "skipped": 0, "fail": 1} # 计为1次失败

    album_title, total_album_pages = parse_album_info(first_page_html)
    album_dir = os.path.join(save_root, album_title)
    os.makedirs(album_dir, exist_ok=True)
    logging.info("专辑 '%s' 共 %d 页", album_title, total_album_pages)

    # 2. 收集专辑内所有分页的图片文件名
    all_image_filenames = set()
    all_image_filenames.update(parse_images_on_album_page(first_page_html))

    for page_num in range(2, total_album_pages + 1):
        page_url = f"{album_url.rstrip('/')}/{page_num}/"
        page_html = request_text(session, page_url, retries=args.retries, timeout=args.timeout)
        if page_html:
            filenames = parse_images_on_album_page(page_html)
            all_image_filenames.update(filenames)
            logging.info("解析专辑分页: %s (找到 %d 张图片)", page_url, len(filenames))
        else:
            logging.warning("获取专辑分页失败: %s", page_url)

    if not all_image_filenames:
        logging.warning("在专辑 [%s] 中未解析到任何图片", album_title)
        return {"ok": 0, "skipped": 0, "fail": 0}
        
    # 3. 对所有图片进行并发下载
    logging.info("准备为 '%s' 下载 %d 张图片...", album_title, len(all_image_filenames))
    results = {"ok": 0, "skipped": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=args.image_concurrency) as executor:
        future_map = {executor.submit(download_single_image, session, fname, album_dir, args): fname for fname in all_image_filenames}
        for future in as_completed(future_map):
            try:
                status = future.result()
                results[status] += 1
            except Exception:
                fname = future_map[future]
                logging.exception("图片下载任务异常 [%s]", fname)
                results["fail"] += 1
    
    logging.info("专辑 '%s' 处理完成. 结果: %s", album_title, results)
    return results

# -------- 主函数 --------
def main():
    parser = argparse.ArgumentParser(description="Meiru.neocities.org 图集爬虫 (高质量重构版)", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="图片保存的根目录")
    parser.add_argument("--start", type=int, default=1, help="起始列表页码")
    parser.add_argument("--end", type=int, default=0, help="结束列表页码 (0 代表自动检测)")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求失败最大重试次数")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时时间(秒)")
    parser.add_argument("-c", "--album-concurrency", type=int, default=DEFAULT_CONCURRENCY_ALBUM, help="并发处理的专辑数量")
    parser.add_argument("-w", "--image-concurrency", type=int, default=DEFAULT_CONCURRENCY_IMAGE, help="每个专辑内部并发下载图片数")
    parser.add_argument("--page-sleep", type=float, default=DEFAULT_PAGE_SLEEP, help="爬取每个列表页后的基础延迟(秒)")
    parser.add_argument("--image-sleep", type=float, default=DEFAULT_IMAGE_SLEEP, help="每张图片下载成功后的延迟(秒)")
    args = parser.parse_args()

    save_root = os.path.abspath(args.dir)
    os.makedirs(save_root, exist_ok=True)
    session = make_session()

    logging.info("请求首页以获取主站总页数...")
    home_html = request_text(session, BASE_URL, retries=args.retries, timeout=args.timeout)
    if not home_html:
        logging.critical("无法获取网站首页，程序退出。")
        return
        
    total_site_pages = parse_max_page_number(BeautifulSoup(home_html, 'html.parser'))
    logging.info("检测到主站总页数: %d", total_site_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end > 0 and args.end >= start_page else total_site_pages
    
    summary = {"ok": 0, "skipped": 0, "fail": 0, "albums_processed": 0}
    seen_album_urls: Set[str] = set()
    
    with ThreadPoolExecutor(max_workers=args.album_concurrency) as executor:
        future_map = {}
        for page_num in range(start_page, end_page + 1):
            page_url = f"{BASE_URL}/page/{page_num}/" if page_num > 1 else BASE_URL
            logging.info("开始处理列表页 %d/%d -> %s", page_num, end_page, page_url)
            
            list_html = request_text(session, page_url, retries=args.retries, timeout=args.timeout)
            if not list_html: continue
            
            for album_url in parse_albums_on_listing_page(list_html):
                if album_url in SKIP_URLS:
                    logging.info("根据配置跳过: %s", album_url)
                    continue
                if album_url not in seen_album_urls:
                    seen_album_urls.add(album_url)
                    future = executor.submit(process_album, session, album_url, save_root, args)
                    future_map[future] = album_url
            
            time.sleep(args.page_sleep + random.random())

        logging.info("所有列表页遍历完毕，等待 %d 个专辑任务完成...", len(future_map))
        for future in as_completed(future_map):
            album_url = future_map[future]
            try:
                result = future.result()
                summary["ok"] += result["ok"]
                summary["skipped"] += result["skipped"]
                summary["fail"] += result["fail"]
                summary["albums_processed"] += 1
            except Exception:
                logging.exception("处理专辑 [%s] 时发生未捕获的异常", album_url)
    
    logging.info("=" * 50)
    logging.info("所有任务完成！")
    logging.info(
        "处理专辑数: %d, 成功下载: %d, 跳过: %d, 失败: %d",
        summary["albums_processed"], summary["ok"], summary["skipped"], summary["fail"]
    )
    logging.info("=" * 50)


if __name__ == "__main__":
    main()
