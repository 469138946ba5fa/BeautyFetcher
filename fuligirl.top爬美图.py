#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fuligirl图集爬虫 (高质量重构版)

功能:
  - 爬取 fuligirl.top 网站的图集。

流程:
  主页 -> 获取总页数 -> 遍历所有列表页 -> 提取专辑链接
     └-> (并发处理) -> 进入专辑页 -> 获取专辑内总页数
          └-> 遍历专辑内所有分页 -> 提取图片链接
               └-> (并发下载) -> 下载图片并保存

特点:
  - 两级并发: 并发处理多个图集，同时在每个图集内部并发下载图片。
  - 请求重试: 内置指数退避和随机抖动的请求重试机制，应对网络波动。
  - 原子化写入: 下载图片时先写入临时文件，完成后再重命名，防止文件损坏。
  - 断点续传: 自动跳过已存在的图片文件。
  - 内存高效: 采用“边发现边处理”的模式，无需将所有专辑信息读入内存。
  - 灵活配置: 通过命令行参数可自定义并发数、延迟、保存目录等。
  - 健壮的解析: 使用更稳定的CSS选择器，并有清晰的日志记录。
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
from bs4 import BeautifulSoup, Tag

# -------- 默认配置 --------
BASE_URL = "https://fuligirl.top"
# 可靠的图片CDN列表，程序会自动尝试
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

# -------- 日志设置 --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# -------- 辅助函数 (从高质量范例中借鉴和优化) --------
def make_session() -> requests.Session:
    """创建一个配置好 User-Agent 的 requests.Session 对象"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36",
        "Referer": BASE_URL
    })
    return s

def request_text(session: requests.Session, url: str, retries: int = DEFAULT_RETRIES, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """请求文本页面，带重试和指数退避，返回 text 或 None。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200 and r.text:
                return r.text
            logging.warning("非200或空响应: %s -> %s", url, r.status_code)
        except requests.RequestException as e:
            logging.warning("请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        # 指数退避 + 随机抖动
        time.sleep(min(10, (2 ** attempt) * 0.3) + random.random())
    return None

def request_binary(session: requests.Session, url: str, retries: int = DEFAULT_RETRIES, timeout: int = DEFAULT_TIMEOUT) -> Optional[bytes]:
    """请求二进制(图片)，返回 bytes 或 None。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True)
            if r.status_code == 200:
                return r.content
            logging.warning("图片请求非200: %s -> %s", url, r.status_code)
        except requests.RequestException as e:
            logging.warning("图片请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.25) + random.random())
    return None

def sanitize_filename(name: str, maxlen: int = 150) -> str:
    """把文件夹/文件名里不安全的字符替换掉，并截断长度。"""
    if not name:
        return "untitled"
    name = unquote(name)
    s = re.sub(r'[\0\/\\:\*\?\"<>\|]+', "_", name).strip()
    return s[:maxlen] or "untitled"

def save_bytes_atomic(path: str, data: bytes) -> bool:
    """原子化写入文件，避免文件损坏。"""
    tmp_path = path + ".part"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
        return True
    except IOError as e:
        logging.error("文件写入失败 %s : %s", path, e)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

# -------- 解析函数 --------
def parse_total_pages(soup: BeautifulSoup) -> int:
    """从导航元素中解析总页数，逻辑更健壮。"""
    page_links = soup.select('nav.my-2 a[href*="?page="]')
    if not page_links:
        return 1
    
    last_page_num = 0
    for link in page_links:
        href = link.get('href', '')
        match = re.search(r'\?page=(\d+)', href)
        if match:
            last_page_num = max(last_page_num, int(match.group(1)))
            
    return last_page_num if last_page_num > 0 else 1

def parse_albums_on_page(html: str) -> List[Tuple[str, str]]:
    """从列表页HTML中解析出所有专辑的 (URL, 标题)。"""
    soup = BeautifulSoup(html, 'html.parser')
    albums = []
    # 选择器更精确，直接定位到包含链接和标题的父级div
    for div in soup.select('div.my-1:not([class*=" "])'):
        a_tag = div.find('a', href=True)
        h2_tag = div.find('h2', class_='font-semibold')
        if a_tag and h2_tag:
            url = urljoin(BASE_URL, a_tag['href'])
            title = sanitize_filename(h2_tag.get_text(strip=True))
            albums.append((url, title))
    return albums

def parse_images_on_album_page(html: str) -> List[str]:
    """从专辑的单个分页HTML中解析出所有图片的原始文件名。"""
    soup = BeautifulSoup(html, 'html.parser')
    image_filenames = []
    # 定位到图片容器，然后提取所有图片
    container = soup.select_one('div.pt-4')
    if container:
        for img in container.select('img.block.my-1[src]'):
            src = img['src']
            filename = src.split('/')[-1]
            if filename:
                image_filenames.append(filename)
    return image_filenames

# -------- 下载核心逻辑 --------
def download_single_image(session: requests.Session, filename: str, album_dir: str, retries: int, image_sleep: float) -> str:
    """下载单张图片，包含检查存在、重试、原子写入的完整逻辑。返回状态字符串。"""
    dest_path = os.path.join(album_dir, sanitize_filename(filename))
    if os.path.exists(dest_path):
        logging.debug("已存在，跳过: %s", dest_path)
        return "skipped"

    # 遍历所有可用图片源进行尝试
    img_content = None
    tried_urls = []
    for tg_url_base in TG_URLS:
        img_url = f"{tg_url_base}/{filename}"
        tried_urls.append(img_url)
        img_content = request_binary(session, img_url, retries=2) # 每个源重试2次即可
        if img_content:
            break # 下载成功，跳出循环
    
    if not img_content:
        logging.warning("下载失败 (尝试了 %d 个源): %s", len(TG_URLS), tried_urls)
        return "fail"
        
    if save_bytes_atomic(dest_path, img_content):
        logging.info("下载成功: %s", dest_path)
        time.sleep(image_sleep + random.random() * 0.2)
        return "ok"
    else:
        return "fail"

# -------- 专辑处理主流程 --------
def process_album(session: requests.Session, album_url: str, album_title: str, save_root: str, args: argparse.Namespace) -> Dict[str, int]:
    """处理单个专辑的完整流程：获取所有图片链接 -> 并发下载。"""
    logging.info("开始处理专辑: %s", album_title)
    album_dir = os.path.join(save_root, album_title)
    os.makedirs(album_dir, exist_ok=True)
    
    first_page_html = request_text(session, album_url, retries=args.retries)
    if not first_page_html:
        logging.error("无法获取专辑首页内容: %s", album_url)
        return {"ok": 0, "skipped": 0, "fail": 0}

    soup = BeautifulSoup(first_page_html, 'html.parser')
    total_album_pages = parse_total_pages(soup)
    logging.info("专辑 [%s] 共 %d 页", album_title, total_album_pages)
    
    all_image_filenames = []
    # 1. 收集所有分页的图片文件名
    for page_num in range(1, total_album_pages + 1):
        if page_num == 1:
            page_html = first_page_html
            page_url = album_url
        else:
            page_url = f"{album_url}?page={page_num}"
            page_html = request_text(session, page_url, retries=args.retries)
        
        if page_html:
            logging.info("解析专辑分页: %s", page_url)
            filenames = parse_images_on_album_page(page_html)
            all_image_filenames.extend(filenames)
        else:
            logging.warning("获取专辑分页失败: %s", page_url)

    if not all_image_filenames:
        logging.warning("在专辑 [%s] 中未解析到任何图片", album_title)
        return {"ok": 0, "skipped": 0, "fail": 0}
        
    # 2. 对收集到的所有图片进行并发下载
    logging.info("准备为专辑 [%s] 下载 %d 张图片...", album_title, len(all_image_filenames))
    results = {"ok": 0, "skipped": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=args.image_concurrency) as executor:
        future_map = {
            executor.submit(download_single_image, session, filename, album_dir, args.retries, args.image_sleep): filename
            for filename in set(all_image_filenames) # 去重
        }
        for future in as_completed(future_map):
            try:
                status = future.result()
                results[status] += 1
            except Exception as e:
                filename = future_map[future]
                logging.error("图片下载任务异常 [%s]: %s", filename, e)
                results["fail"] += 1
                
    return results

# -------- 主函数 --------
def main():
    parser = argparse.ArgumentParser(
        description="Fuligirl.top 图集爬虫 (高质量重构版)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="图片保存的根目录")
    parser.add_argument("--start", type=int, default=1, help="起始列表页码")
    parser.add_argument("--end", type=int, default=0, help="结束列表页码 (0 代表自动检测到最后一页)")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求失败时的最大重试次数")
    parser.add_argument("-c", "--album-concurrency", type=int, default=DEFAULT_CONCURRENCY_ALBUM, help="并发处理的专辑数量")
    parser.add_argument("-w", "--image-concurrency", type=int, default=DEFAULT_CONCURRENCY_IMAGE, help="每个专辑内部并发下载的图片数量")
    parser.add_argument("--page-sleep", type=float, default=DEFAULT_PAGE_SLEEP, help="每爬取一个列表页后的基础延迟(秒)")
    parser.add_argument("--image-sleep", type=float, default=DEFAULT_IMAGE_SLEEP, help="每张图片下载成功后的基础延迟(秒)")
    args = parser.parse_args()

    save_root = os.path.abspath(args.dir)
    os.makedirs(save_root, exist_ok=True)
    session = make_session()

    logging.info("请求首页以获取总页数...")
    home_html = request_text(session, BASE_URL, retries=args.retries)
    if not home_html:
        logging.error("无法获取网站首页，程序退出。")
        return
        
    total_site_pages = parse_total_pages(BeautifulSoup(home_html, 'html.parser'))
    logging.info("检测到网站总页数: %d", total_site_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end > 0 and args.end >= start_page else total_site_pages

    summary = {"ok": 0, "skipped": 0, "fail": 0, "albums_processed": 0}
    seen_album_urls: Set[str] = set()

    # 主流程：边发现，边提交任务到线程池，内存高效
    with ThreadPoolExecutor(max_workers=args.album_concurrency) as executor:
        future_map = {}
        for page_num in range(start_page, end_page + 1):
            page_url = f"{BASE_URL}/?page={page_num}" if page_num > 1 else BASE_URL
            logging.info("开始处理列表页 %d/%d -> %s", page_num, end_page, page_url)
            
            list_html = request_text(session, page_url, retries=args.retries)
            if not list_html:
                logging.warning("获取列表页失败: %s", page_url)
                continue
            
            albums_on_page = parse_albums_on_page(list_html)
            logging.info("本页找到 %d 个专辑", len(albums_on_page))
            
            for album_url, album_title in albums_on_page:
                if album_url not in seen_album_urls:
                    seen_album_urls.add(album_url)
                    future = executor.submit(process_album, session, album_url, album_title, save_root, args)
                    future_map[future] = (album_url, album_title)
            
            time.sleep(args.page_sleep + random.random())

        logging.info("所有列表页遍历完毕，等待 %d 个专辑任务完成...", len(future_map))
        for future in as_completed(future_map):
            album_url, album_title = future_map[future]
            try:
                result = future.result()
                summary["ok"] += result["ok"]
                summary["skipped"] += result["skipped"]
                summary["fail"] += result["fail"]
                summary["albums_processed"] += 1
            except Exception as e:
                logging.error("处理专辑 [%s] 时发生未捕获的异常: %s", album_title, e)

    logging.info("=" * 50)
    logging.info("所有任务完成！")
    logging.info(
        "处理专辑数: %d, 成功下载: %d, 跳过: %d, 失败: %d",
        summary["albums_processed"], summary["ok"], summary["skipped"], summary["fail"]
    )
    logging.info("=" * 50)

if __name__ == "__main__":
    main()
