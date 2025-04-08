# 思路
'''
    在脚本所在目录下创建 美女图集 文件夹并进入文件夹，如果存在则忽略创建直接进入目录,创建重试函数，为了规避网络问题导致的 tls 报错，并且使用脚本实现需求
    定义 跳过链接集
    创建判断链接是在跳过链接集中存在，并返回布尔
    定义 a_url 为 https://xerocos.com
    请求 a_url 若为 200 且有内容则返回 a_content

    从 a_content 中最后一个 <div class="flex space-x-2"></div> 元素中获得<div class="hidden md:block"></div> 并从中获取 <a class="hover:bg-pink-500 bg-gray-700 relative inline-flex items-center px-4 py-2 border border-pink-500 text-xs font-medium rounded-md text-gray-100" href="">Last</a> 从 href 属性中得到总页数(比如得到了 /?page=226 则返回总页数 226) a_pager

    从 1 开始循环便利总页数到 a_pager 范围 [1,a_pager+1]
    当为 1 则拼接 a_url 对应的链接赋值给 a_pager_url ，将 a_content 赋值给 a_pager_url_content
    当不为1 则拼接 a_url + a_pager 得到类似 https://xerocos.com/?page=2 的拼接其中 /?page=2 代表第2页之后的拼接以此类推，得到拼接 a_pager_url ，请求 a_pager_url 若为 200 且有内容则返回 a_pager_url_content
    
    从 a_pager_url_content 中 <div class="group flex-shrink-0 pb-3"></div> 中匹配 <div class="pt-2"></div> 中匹配 <div class="flex items-center flex-wrap"></div> 中匹配 <a href=""></a> 提取全部的链接 b_url 和对应链接名 b_name（废除项） 并统计返回数量 b_count

    从 0 开始循环便利总数到 b_count 范围 [0,b_count]
    在当前目录下创建对应的 b_name 目录并进入目录，如果存在则不创建目录直接进入目录（废除项）
    拼接 a_url+b_url 对应的链接并请求，若为 200 且有内容则返回 b_content

    从 b_content 中最后一个 <div class="flex space-x-2"></div> 元素中获得<div class="hidden md:block"></div> 并从中获取 <a class="hover:bg-pink-500 bg-gray-700 relative inline-flex items-center px-4 py-2 border border-pink-500 text-xs font-medium rounded-md text-gray-100" href="">Last</a> 从 href 属性中得到总页数(比如得到了 /?page=226 则返回总页数 226) b_pager ，如果没有获取到 <div class="flex space-x-2"></div> 则说明只有1页默认返回 1 即 b_pager=1

    从 1 开始循环便利总页数到 b_pager 范围 [1,b_pager+1]
    当为 1 则拼接 a_url+b_url 对应的链接赋值给 a_b_pager_url，将 b_content 赋值给 a_b_pager_url_content
    当不为 1 则拼接 a_url+b_url 和 b_pager 得到类似 https://xerocos.com/tag/bowsette?page=2 的拼接，其中 https://xerocos.com 是 a_url，/tag/bowsette 是 b_url， ?page=2 代表第2页之后的拼接以此类推，得到拼接 a_b_pager_url 并请求，若为 200 且有内容则返回 a_b_pager_url_content
    
    从 a_b_pager_url_content 中获取 <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 pb-6"></div> 元素并从中匹配全部的 <div class="group flex-shrink-0 pb-3"></div> 中匹配 <div class="relative overflow-hidden rounded-sm shadow-xl latest-card"></div> 中匹配  <a href=""></a> 的链接 c_url 和 <a href=""></a> 中匹配 <img alt="" class="duration-100 ease-in-out group-hover:opacity-75 scale-100 blur-0 grayscale-0" src=""> 的 alt 文件夹名 c_name 并统计总数量 c_count

    从 0 开始循环便利总数到 c_count 范围 [0,c_count]
    创建对应的 c_name 目录并进入目录，如果存在则不创建目录直接进入目录
    拼接 a_url+c_url 对应的链接并请求 若为 200 且有内容则返回 c_content

    从 c_content 中最后一个 <div class="flex items-center my-2 flex-wrap"></div> 元素中获取最后一个 <a rel="" class="" href=""></a> 元素并得到文本值总页数(比如得到了 2 则返回总页数 2) c_pager ，如果没有获取到 <div class="flex items-center my-2 flex-wrap"></div> 则说明只有1页默认返回 1 即 c_pager=1

    从 1 开始循环便利总页数到 c_pager 范围 [1,c_pager+1]
    当为 1 则拼接 a_url+c_url 对应的链接赋值给 a_c_pager_url ，将 c_content 赋值给 a_c_pager_url_content
    当不为 1 则拼接 a_url+c_url 和 c_pager 得到类似 https://xerocos.com/view/nagisa-bowsette?page=2 的拼接，其中 https://xerocos.com 是 a_url ，/view/nagisa-bowsette 是 c_url ， ?page=2 代表第2页之后的拼接以此类推，得到拼接 a_c_pager_url 并请求，若为 200 且有内容则返回 a_c_pager_url_content
    判断 a_url+c_url 是否在跳过链接集中，如果存在则打印链接+存在跳过不进行获取 continue 如果不存在则打印链接+不存在，继续运行
    
    从 a_c_pager_url_content 中的 <div class="max-w-7xl mx-auto px-4 w-full"></div> 中匹配 <div class="md:px-16 xl:px-20 max-w-3xl mx-auto justify-center items-center flex flex-col min-h-screen"></div> 的 <div></div> 的 <img alt="" class="" src="" data-src="" > 中匹配 data-src 获取全部图片链接 d_url ，并得到图片链接总数量 d_count
    
    从 0 开始循环便利总数到 d_count 范围 [0,d_count]
    处理图片链接 d_url 并截取文件名得到 d_name ，检查文件路径中是否与 d_name 重名，如果找到重名文件则代表文件存在也就不用请求图片链接，如果找不到重名文件则说明文件不存在则请求图片链接并存储下载并截取文件名存储到 c_name 目录中，比如获取的链接为 https://i1.wp.com/mitaku.net/wp-content/uploads/2021/07/Nagisa-%E9%AD%94%E7%89%A9%E5%96%B5-Bowsette-1.jpg 那么存储的文件名就为 Nagisa-%E9%AD%94%E7%89%A9%E5%96%B5-Bowsette-1.jpg 并睡眠3s

总结:
模块化设计 各步骤均封装为独立函数：

request_with_retry 封装了带重试机制的 HTTP 请求。

parse_total_pages_from_nav 从页面导航提取总页数。

get_galleries_from_listing 从专辑列表页中提取每个专辑的链接与标题。

process_gallery 则负责处理单个专辑的分页和图片下载。

process_listing_pages 对主列表页逐页解析专辑。

并发处理 采用 ThreadPoolExecutor 对所有专辑进行并发调度，提高整体爬取速度。

日志和参数化 使用 logging 输出详细消息，同时通过 argparse 允许用户灵活指定目标目录、重试次数、休眠时间及并发数
'''
# python3 -m pip install requests beautifulsoup4
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import re
import logging
import random
import argparse
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ---------------------- 全局配置参数 ----------------------
BASE_URL = "https://xerocos.com"
TARGET_DIR = "美女图集"
RETRY_MAX = 5
PAGE_SLEEP = 10      # 每个分页处理后等待时间（秒）
IMAGE_SLEEP = 3      # 每张图片下载后等待时间（秒）
CONCURRENCY = 4      # 并发处理专辑数量

# ---------------------- 跳过链接集 ----------------------
SKIP_URLS = {
    "https://xerocos.com/view/aqua-kiara-sessyoin",
}

# ---------------------- 日志设置 ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------------------- 辅助函数 ----------------------
def create_directory(path):
    """创建目录（不存在则创建），返回绝对路径。"""
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.abspath(path)

def sanitize_filename(filename):
    """过滤文件名中的非法字符。"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def request_with_retry(session, url, max_retries=RETRY_MAX):
    """
    使用传入的 session 发送 GET 请求，内置重试机制。
    若响应状态码为200且有内容，则返回 response.content，否则返回 None。
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=10)
            if response.status_code == 200 and response.content:
                return response.content
            else:
                raise Exception(f"Status code: {response.status_code}")
        except Exception as e:
            logging.error("Error requesting %s: %s (Attempt %d/%d)", url, e, attempt, max_retries)
            time.sleep(random.uniform(2, 5))
    return None

def check_url_exists(test_url):
    """判断给定链接是否在跳过链接集中。"""
    return test_url in SKIP_URLS

def parse_last_page_href(soup, selector):
    """
    根据传入的 CSS 选择器，从分页区域中提取“Last”链接的 href，解析出总页数。
    例如：从 href="/?page=226" 得到226。
    若解析失败，则默认返回1。
    """
    try:
        last_page_link = soup.select_one(selector)
        if last_page_link and 'href' in last_page_link.attrs:
            return int(last_page_link['href'].split('=')[-1])
    except Exception as e:
        logging.error("Error parsing last page: %s", e)
    return 1
def process_detail_images(session, detail_url, output_folder, image_sleep=IMAGE_SLEEP):
    """
    处理详情页面 (detail_url)：
      1. 获取详情页内容，解析分页数；
      2. 遍历每一分页，从中提取图片链接（data-src），并下载到 output_folder。
    为防止相对路径出错，所有提取的 URL 均使用 urljoin 生成绝对链接。
    """
    c_content = request_with_retry(session, detail_url)
    if not c_content:
        logging.error("Failed to fetch detail page: %s", detail_url)
        return
    c_soup = BeautifulSoup(c_content, "html.parser")
    pager_links = c_soup.select("div.flex.items-center.my-2.flex-wrap a[rel][class][href]")
    try:
        c_pager = int(pager_links[-1].text) if pager_links else 1
    except Exception:
        c_pager = 1
    logging.info("Detail page %s total pages: %d", detail_url, c_pager)
    for m in range(1, c_pager + 1):
        if m == 1:
            a_c_pager_url = detail_url
            a_c_pager_content = c_content
        else:
            a_c_pager_url = f"{detail_url}?page={m}"
            a_c_pager_content = request_with_retry(session, a_c_pager_url)
            if not a_c_pager_content:
                logging.error("Failed to fetch detail pagination: %s", a_c_pager_url)
                continue
        # 这里修正为直接使用 a_c_pager_content，不再使用不存在的 a_c_pager_url_content
        detail_soup = BeautifulSoup(a_c_pager_content, "html.parser")
        images = detail_soup.select(
            "div.max-w-7xl.mx-auto.px-4.w-full div.md\\:px-16.xl\\:px-20.max-w-3xl.mx-auto.justify-center.items-center.flex.flex-col.min-h-screen div img[alt][class][data-src]"
        )
        # 对每个 data-src 使用 urljoin(detail_url, ...) 生成绝对 URL
        d_urls = [urljoin(detail_url, img['data-src']) for img in images]
        logging.info("Found %d images on detail page %s", len(d_urls), a_c_pager_url)
        for n, d_url in enumerate(d_urls):
            filename = d_url.split("/")[-1]
            d_path = os.path.join(output_folder, filename)
            if os.path.exists(d_path):
                logging.info("Image already exists: %s", d_path)
                continue
            logging.info("Downloading image %d/%d: %s", n+1, len(d_urls), d_url)
            d_content = request_with_retry(session, d_url)
            if not d_content:
                logging.error("Failed to download image: %s", d_url)
                continue
            try:
                with open(d_path, "wb") as f:
                    f.write(d_content)
            except Exception as e:
                logging.error("Error saving image to %s: %s", d_path, e)
            time.sleep(image_sleep)

def process_gallery_page(session, b_url, output_dir, retry=RETRY_MAX, page_sleep=PAGE_SLEEP, image_sleep=IMAGE_SLEEP):
    """
    处理单个专辑页面 (b_url)：
      1. 获取专辑首页，解析出专辑内分页总数（b_pager）。
      2. 遍历各分页，提取详情条目（详情链接 c_url 及对应名称 c_name）。
      3. 对每个详情链接，若不在跳过集合中，调用 process_detail_images 下载详情页图片。
    """
    b_content = request_with_retry(session, b_url, max_retries=retry)
    if not b_content:
        logging.error("Failed to fetch gallery page: %s", b_url)
        return
    b_soup = BeautifulSoup(b_content, "html.parser")
    b_pager = parse_last_page_href(
        b_soup,
        'div.flex.space-x-2 div.hidden.md\\:block a.hover\\:bg-pink-500.bg-gray-700.relative.inline-flex.items-center.px-4.py-2.border.border-pink-500.text-xs.font-medium.rounded-md.text-gray-100[href]'
    )
    logging.info("Gallery page %s total pages: %d", b_url, b_pager)
    for k in range(1, b_pager + 1):
        if k == 1:
            a_b_pager_url = b_url
            a_b_pager_content = b_content
        else:
            a_b_pager_url = f"{b_url}?page={k}"
            a_b_pager_content = request_with_retry(session, a_b_pager_url, max_retries=retry)
            if not a_b_pager_content:
                logging.error("Failed to fetch gallery pagination: %s", a_b_pager_url)
                continue
        logging.info("Processing gallery sub-page: %s", a_b_pager_url)
        ab_soup = BeautifulSoup(a_b_pager_content, "html.parser")
        links = ab_soup.select(
            'div.grid.grid-cols-2.md\\:grid-cols-3.lg\\:grid-cols-4.gap-4.pb-6 div.group.flex-shrink-0.pb-3 div.relative.overflow-hidden.rounded-sm.shadow-xl.latest-card a[href]'
        )
        c_urls = [link['href'] for link in links]
        c_names = [link.img.get('alt', 'Unknown') for link in links if link.img]
        c_count = len(c_urls)
        logging.info("Found %d detail entries on page %s", c_count, a_b_pager_url)
        for l in range(c_count):
            folder_name = sanitize_filename(c_names[l].replace(":", " ").replace("：", " ").replace(" ", "-"))
            folder_path = create_directory(os.path.join(output_dir, folder_name))
            logging.info("Processing detail: %s -> %s", c_urls[l], folder_path)
            c_full_url = urljoin(BASE_URL, c_urls[l])
            if check_url_exists(c_full_url):
                logging.info("Skip URL (exists in skip set): %s", c_full_url)
                continue
            c_content = request_with_retry(session, c_full_url, max_retries=retry)
            if not c_content:
                logging.error("Failed to fetch detail page: %s", c_full_url)
                continue
            process_detail_images(session, c_full_url, folder_path, image_sleep=image_sleep)
def process_home_page(session, base_url, retry=RETRY_MAX):
    """
    请求首页 (a_url)，解析出总分页数，并构造所有列表页的 URL 列表。
    """
    a_content = request_with_retry(session, base_url, max_retries=retry)
    if not a_content:
        logging.error("Failed to fetch home page: %s", base_url)
        return []
    a_soup = BeautifulSoup(a_content, "html.parser")
    a_pager = parse_last_page_href(
        a_soup,
        'div.flex.space-x-2 div.hidden.md\\:block a.hover\\:bg-pink-500.bg-gray-700.relative.inline-flex.items-center.px-4.py-2.border.border-pink-500.text-xs.font-medium.rounded-md.text-gray-100[href]'
    )
    logging.info("Home page total pages: %d", a_pager)
    home_pages = []
    for i in range(1, a_pager + 1):
        if i == 1:
            home_pages.append(base_url)
        else:
            home_pages.append(f"{base_url}/?page={i}")
    return home_pages

def process_listing_page(session, page_url):
    """
    处理列表页，提取所有专辑链接，并返回完整链接列表。
    """
    content = request_with_retry(session, page_url, max_retries=RETRY_MAX)
    if not content:
        logging.error("Failed to fetch listing page: %s", page_url)
        return []
    soup = BeautifulSoup(content, "html.parser")
    links = soup.select('div.group.flex-shrink-0.pb-3 div.pt-2 div.flex.items-center.flex-wrap a[href]')
    gallery_paths = [link['href'] for link in links]
    gallery_urls = [urljoin(BASE_URL, path) for path in gallery_paths]
    logging.info("Found %d galleries on listing page: %s", len(gallery_urls), page_url)
    return gallery_urls

def main():
    parser = argparse.ArgumentParser(description="极致重构的 xerocos.com 爬虫")
    parser.add_argument('-d', '--dir', default=TARGET_DIR, help=f"目标存储目录（默认: {TARGET_DIR}）")
    parser.add_argument('-r', '--retries', type=int, default=RETRY_MAX, help=f"请求重试次数（默认: {RETRY_MAX}）")
    parser.add_argument('--page_sleep', type=float, default=PAGE_SLEEP, help=f"分页处理后等待时间（秒，默认: {PAGE_SLEEP}）")
    parser.add_argument('--image_sleep', type=float, default=IMAGE_SLEEP, help=f"单张图片下载后等待时间（秒，默认: {IMAGE_SLEEP}）")
    parser.add_argument('-c', '--concurrency', type=int, default=CONCURRENCY, help=f"并发处理专辑数量（默认: {CONCURRENCY}）")
    args = parser.parse_args()

    output_dir = create_directory(args.dir)
    logging.info("图片存储目录: %s", output_dir)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/58.0.3029.110 Safari/537.3"
    })

    os.chdir(output_dir)
    logging.info("当前工作目录: %s", os.path.abspath('.'))

    home_pages = process_home_page(session, BASE_URL, retry=args.retries)
    all_galleries = []
    for page_url in home_pages:
        galleries = process_listing_page(session, page_url)
        all_galleries.extend(galleries)
        time.sleep(3)
    logging.info("Total galleries found: %d", len(all_galleries))

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(process_gallery_page, session, gallery_url, output_dir, args.retries, args.page_sleep, args.image_sleep): gallery_url for gallery_url in all_galleries}
        for future in as_completed(futures):
            gallery_url = futures[future]
            try:
                future.result()
            except Exception as e:
                logging.error("Error processing gallery %s: %s", gallery_url, e)
    session.close()
    logging.info("All tasks completed.")

if __name__ == "__main__":
    main()
