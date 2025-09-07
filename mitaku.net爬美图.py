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

import requests
from bs4 import BeautifulSoup

# -------- 默认配置 --------
BASE_URL = "https://mitaku.net"
DEFAULT_SAVE_DIR = "美女图集"
DEFAULT_RETRIES = 5
DEFAULT_CONCURRENCY = 6            # 并发处理专辑数量
DEFAULT_WORKERS_PER_ALBUM = 6      # 专辑内部并发下载数
DEFAULT_PAGE_SLEEP = 10.0
DEFAULT_IMAGE_SLEEP = 3.0
DEFAULT_TIMEOUT = 15

# 日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# -------- 辅助函数 --------
def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                      " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    })
    return s


def request_text(session, url, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """请求文本页面，带重试和随机退避，返回 text 或 None。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200 and r.text:
                return r.text
            logging.warning("非200或空响应: %s -> %s", url, r.status_code)
        except Exception as e:
            logging.warning("请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.3) + random.random())
    return None


def request_binary(session, url, retries=DEFAULT_RETRIES, timeout=DEFAULT_TIMEOUT):
    """请求二进制（图片），返回 bytes 或 None。"""
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, timeout=timeout, stream=True) as r:
                if r.status_code == 200:
                    return r.content
                logging.warning("图片请求非200: %s -> %s", url, r.status_code)
        except Exception as e:
            logging.warning("图片请求失败: %s (尝试 %d/%d) 错误: %s", url, attempt, retries, e)
        time.sleep(min(10, (2 ** attempt) * 0.25) + random.random())
    return None


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    """把文件夹/文件名里不安全的字符替换掉，并截断长度。"""
    if not name:
        return "untitled"
    name = unquote(name)
    # 替换控制字符与文件系统禁用字符为下划线
    s = re.sub(r'[\0\/\\\:\*\?\"\<\>\|]+', "_", name)
    s = s.strip()
    return s[:maxlen] or "untitled"


# -------- 解析函数 --------
def get_total_pages_from_home(html: str) -> int:
    """
    从首页解析总页数：
    优先使用 div.wp-pagenavi span.pages 内容 'Page 1 of N'
    兜底：使用 div.wp-pagenavi a.last href -> /page/N/
    """
    soup = BeautifulSoup(html, "html.parser")
    span = soup.select_one("div.wp-pagenavi span.pages")
    if span and span.get_text(strip=True):
        m = re.search(r'of\s+(\d+)', span.get_text(), re.I)
        if m:
            try:
                return int(m.group(1))
            except:
                pass
    a_last = soup.select_one("div.wp-pagenavi a.last[href]")
    if a_last:
        href = a_last["href"]
        m2 = re.search(r'/page/(\d+)/', href)
        if m2:
            return int(m2.group(1))
    # 再兜底：找所有 /page/N/ 并取最大
    hrefs = [a.get("href", "") for a in soup.select("div.wp-pagenavi a[href]")]
    nums = []
    for h in hrefs:
        m = re.search(r'/page/(\d+)/', h)
        if m:
            nums.append(int(m.group(1)))
    if nums:
        return max(nums)
    return 1


def parse_listing_page_for_albums(html: str):
    """
    从列表页（page）中提取专辑列表，返回 list of (title, url)
    优先找到 article .featured-image a 或 h2.entry-title a
    """
    soup = BeautifulSoup(html, "html.parser")
    res = []
    for art in soup.select("article"):
        a = art.select_one(".featured-image a[href]") or art.select_one("h2.entry-title a[href]")
        if a:
            href = a.get("href").strip()
            title = a.get("title") or a.get_text(strip=True) or ""
            res.append((title.strip(), urljoin(BASE_URL, href)))
    return res


def parse_album_first_image_and_count(html: str, album_url: str):
    """
    从专辑详情页提取：
      - post_id（如 article#post-304709）
      - title（entry-title）
      - 第一张图链接（优先 data-mfp-src、然后 img src）
      - 图片总数（文中 'Image: 24 Pics' 格式）
    返回 (post_id_or_None, title_or_None, first_image_url_or_None, total_or_None)
    """
    soup = BeautifulSoup(html, "html.parser")
    # post id
    post_id = None
    art = soup.find("article")
    if art and art.has_attr("id"):
        m = re.match(r'post-(\d+)', art["id"])
        if m:
            post_id = m.group(1)

    # title
    title_tag = soup.select_one("header.entry-header h1.entry-title") or soup.select_one("h1.entry-title") or soup.select_one("h2.entry-title")
    title = title_tag.get_text(strip=True) if title_tag else None

    # first image: 优先 data-mfp-src
    first_img_url = None
    # 1. data-mfp-src on a.msacwl-img-link
    a_tag = soup.select_one("a.msacwl-img-link[data-mfp-src]") or soup.select_one("a[data-mfp-src]")
    if a_tag and a_tag.get("data-mfp-src"):
        first_img_url = urljoin(album_url, a_tag.get("data-mfp-src").split("?")[0])
    else:
        # 2. img inside msacwl-img-wrap 或 img.msacwl-img
        img_tag = soup.select_one("div.msacwl-img-wrap img") or soup.select_one("img.msacwl-img") or soup.select_one("article img")
        if img_tag and img_tag.get("src"):
            first_img_url = urljoin(album_url, img_tag.get("src").split("?")[0])

    # total images: "Image: 24 Pics" in a <p> or anywhere
    total = None
    txt = soup.find(string=re.compile(r"Image\s*:\s*\d+\s*Pics", re.I))
    if not txt:
        # 有时候是 <p style="text-align: center;">Image: 24 Pics</p>
        p = soup.find("p", string=re.compile(r"Image\s*:\s*\d+", re.I))
        if p:
            txt = p.get_text()
    if txt:
        m = re.search(r"Image\s*:\s*(\d+)", txt, re.I)
        if m:
            total = int(m.group(1))

    return post_id, title, first_img_url, total


def build_image_list_from_first(first_url: str, total: int):
    """
    根据第一张图 url (xxx-1.jpg) 和 total，拼接完整列表。
    如果 first_url 不匹配常见 -N 格式，则返回空列表（调用者可回退到其他方法）。
    """
    # 标准形式匹配 ...-<num>.<ext>
    m = re.match(r'(.+?)-(\d+)(\.[A-Za-z0-9]+)$', first_url)
    if not m:
        return []
    prefix, first_num_str, suffix = m.group(1), m.group(2), m.group(3)
    # 以 1..total 生成
    return [f"{prefix}-{i}{suffix}" for i in range(1, total + 1)]


def fallback_collect_images_from_slider(html: str, album_url: str):
    """
    如果详情页无法取得 'Image: N Pics'，回退到从 slider 或 data-mfp-src 中全部抓取链接并按序号排序。
    只在无 total 的极端情况下使用。
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.select("a[data-mfp-src]"):
        v = a.get("data-mfp-src")
        if v:
            found.append(urljoin(album_url, v.split("?")[0]))
    # 尝试 img tags
    for img in soup.find_all("img"):
        for attr in ("data-lazy", "data-src", "src", "data-original"):
            v = img.get(attr)
            if v:
                found.append(urljoin(album_url, v.split("?")[0]))
                break

    # 保留在 uploads 目录的
    seen = []
    for u in found:
        if "/wp-content/uploads/" in u and u not in seen:
            seen.append(u)
    # 尝试按文件名中的序号排序
    def extract_num(u):
        m = re.search(r'-(\d+)(\.[A-Za-z0-9]+)$', u)
        return int(m.group(1)) if m else 0
    seen.sort(key=extract_num)
    return seen


# -------- 下载相关 --------
def save_bytes_atomic(path: str, data: bytes):
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return True
    except Exception as e:
        logging.error("写文件失败 %s : %s", path, e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except:
            pass
        return False


def download_images(session, img_urls, album_dir, retries, workers_per_album, image_sleep):
    os.makedirs(album_dir, exist_ok=True)
    results = {"ok": 0, "skipped": 0, "fail": 0}
    # 并发下载
    def dl_task(url):
        filename = sanitize_filename(urlparse(url).path.split("/")[-1])
        dest = os.path.join(album_dir, filename)
        if os.path.exists(dest):
            logging.info("已存在，跳过: %s", dest)
            return "skipped"
        data = request_binary(session, url, retries=retries)
        if not data:
            logging.warning("下载失败: %s", url)
            return "fail"
        ok = save_bytes_atomic(dest, data)
        if ok:
            logging.info("下载成功: %s", dest)
            # 可选短暂停，避免快速连续请求触发防护
            time.sleep(image_sleep)
            return "ok"
        else:
            return "fail"

    with ThreadPoolExecutor(max_workers=workers_per_album) as ex:
        futures = [ex.submit(dl_task, u) for u in img_urls]
        for fut in as_completed(futures):
            res = None
            try:
                res = fut.result()
            except Exception as e:
                logging.error("图片下载任务异常: %s", e)
                res = "fail"
            results["ok" if res == "ok" else "skipped" if res == "skipped" else "fail"] += 1
    return results


# -------- 专辑处理主流程 --------
def process_album(session, title, url, save_root, retries, workers_per_album, page_sleep, image_sleep):
    """
    进入专辑页 -> 取 post_id/title/first_img/total -> 用 first+total 拼接图片链接（主方法）
    若 total 未找到，回退到从 slider 中收集所有图片链接
    然后下载图片到 <save_root>/<postid - title>/
    """
    logging.info("开始专辑: %s -> %s", title, url)
    html = request_text(session, url, retries=retries)
    if not html:
        logging.error("专辑页面获取失败: %s", url)
        return {"ok": 0, "skipped": 0, "fail": 0}

    post_id, real_title, first_img, total = parse_album_first_image_and_count(html, url)
    # choose name
    folder_name = (post_id + " - " if post_id else "") + (sanitize_filename(real_title or title or url))
    album_dir = os.path.join(save_root, folder_name)

    img_urls = []
    if first_img and total:
        # 主流程：拼接
        img_urls = build_image_list_from_first(first_img, total)
        if not img_urls:
            logging.warning("无法用第一张图拼接（命名格式不匹配），回退到 slider 提取。")
            img_urls = fallback_collect_images_from_slider(html, url)
    elif first_img and not total:
        # 找不到 total，尝试从页面找"Image:"，若还是没有，则回退到 slider
        logging.info("未找到总数，尝试回退到 slider 提取或使用首图推导（若首图带序号）")
        # 尝试从首图名字中猜测是否能拼接：若首以 -1 结尾，尝试推测一个合理上限（不做盲目扩展）
        # 更稳妥的是回退到 slider 提取
        img_urls = fallback_collect_images_from_slider(html, url)
    else:
        # 没有 first_img -> 直接回退 slider 提取
        logging.warning("未找到首图元素，回退到从 slider / data-mfp-src 提取所有图片")
        img_urls = fallback_collect_images_from_slider(html, url)

    if not img_urls:
        logging.warning("未能解析到任何图片链接: %s", url)
        return {"ok": 0, "skipped": 0, "fail": 0}

    # 最终用绝对 url 并去重（保持顺序）
    final = []
    seen = set()
    for u in img_urls:
        absu = urljoin(BASE_URL, u.split("?")[0])
        if absu not in seen:
            seen.add(absu)
            final.append(absu)

    logging.info("准备下载 %d 张图片 到 %s", len(final), album_dir)
    res = download_images(session, final, album_dir, retries, workers_per_album, image_sleep)
    # 小休息
    time.sleep(page_sleep + random.random() * 0.6)
    return res


# -------- 主函数 --------
def main():
    parser = argparse.ArgumentParser(description="mitaku.net 完整爬虫（详情页首图+数量 拼接 -> 下载）")
    parser.add_argument("-d", "--dir", default=DEFAULT_SAVE_DIR, help="保存根目录（默认 images）")
    parser.add_argument("--start", type=int, default=1, help="起始分页（默认 1）")
    parser.add_argument("--end", type=int, default=0, help="结束分页（0 表示首页自动检测到最后一页）")
    parser.add_argument("-r", "--retries", type=int, default=DEFAULT_RETRIES, help="请求重试次数")
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发处理专辑数量")
    parser.add_argument("--workers-per-album", type=int, default=DEFAULT_WORKERS_PER_ALBUM, help="每专辑内部并发图片下载数")
    parser.add_argument("--page-sleep", type=float, default=DEFAULT_PAGE_SLEEP, help="每列表页间隔（秒）")
    parser.add_argument("--image-sleep", type=float, default=DEFAULT_IMAGE_SLEEP, help="每张图片下载后短暂停（秒）")
    args = parser.parse_args()

    save_root = os.path.abspath(args.dir)
    os.makedirs(save_root, exist_ok=True)
    session = make_session()

    # 读取首页获取总页数
    logging.info("请求首页获取总页数: %s", BASE_URL)
    home_html = request_text(session, BASE_URL, retries=args.retries)
    if not home_html:
        logging.error("无法获取首页，退出")
        return
    total_pages = get_total_pages_from_home(home_html)
    logging.info("检到总页数: %d", total_pages)

    start_page = max(1, args.start)
    end_page = args.end if args.end and args.end >= start_page else total_pages

    # 收集所有专辑链接（可逐页直接提交并发处理，这里先收集再处理，若要节省内存可改为边遍历边提交）
    album_entries = []
    for p in range(start_page, end_page + 1):
        page_url = BASE_URL if p == 1 else f"{BASE_URL.rstrip('/')}/page/{p}/"
        logging.info("请求列表页 %d/%d -> %s", p, end_page, page_url)
        page_html = request_text(session, page_url, retries=args.retries)
        if not page_html:
            logging.warning("列表页请求失败: %s", page_url)
            continue
        page_albums = parse_listing_page_for_albums(page_html)
        logging.info("本页找到 %d 个专辑条目", len(page_albums))
        album_entries.extend(page_albums)
        time.sleep(args.page_sleep + random.random() * 0.6)

    # 去重保序
    seen = set()
    albums = []
    for title, url in album_entries:
        if url not in seen:
            seen.add(url)
            albums.append((title, url))
    logging.info("去重后共有 %d 个专辑准备处理", len(albums))

    # 并发处理专辑
    summary = {"ok": 0, "skipped": 0, "fail": 0, "albums": 0}
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        fut_map = {executor.submit(process_album, session, title, url, save_root,
                                    args.retries, args.workers_per_album, args.page_sleep, args.image_sleep): (title, url)
                   for title, url in albums}
        for fut in as_completed(fut_map):
            title, url = fut_map[fut]
            try:
                res = fut.result()
                summary["ok"] += res.get("ok", 0)
                summary["skipped"] += res.get("skipped", 0)
                summary["fail"] += res.get("fail", 0)
                summary["albums"] += 1
            except Exception as e:
                logging.error("专辑处理异常 %s : %s", url, e)
                summary["fail"] += 1

    logging.info("全部完成。专辑数: %d, 成功图片: %d, 跳过图片: %d, 失败图片: %d",
                 summary["albums"], summary["ok"], summary["skipped"], summary["fail"])


if __name__ == "__main__":
    main()
