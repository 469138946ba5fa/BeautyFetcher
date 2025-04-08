# 思路
'''
    在脚本所在目录下创建 美女图集 文件夹并进入文件夹，如果存在则忽略创建直接进入目录,创建重试函数，为了规避网络问题导致的 tls 报错，并且使用脚本实现需求，
    
    定义 a_url 为 https://fuligirl.top
    请求 a_url 若为 200 且有内容则返回 a_content

    从 a_content 中 <nav class="my-2"></nav> 元素中获得 <div></div> 并从中获取 <span></span> 并从 中获取倒数第二个元素 <a href=""></a> 属性中得到总页数(比如得到了 /?page=308 则返回总页数 308) a_pager

    从 1 开始循环便利总页数到 a_pager 范围 [1,a_pager+1]
    当为 1 则拼接 a_url 对应的链接赋值给 a_pager_url ，将 a_content 赋值给 a_pager_url_content
    当不为1 则拼接 a_url + a_pager 得到类似 https://fuligirl.top/?page=2 的拼接其中 /?page=2 代表第2页之后的拼接以此类推，得到拼接 a_pager_url ，请求 a_pager_url 若为 200 且有内容则返回 a_pager_url_content
    
    从 a_pager_url_content 中 <div class="my-1"></div> 中匹配 <a href=""></a> 和 <h2 class="font-semibold"></h2> 提取全部的链接 b_url 和对应链接 h2 标题名 b_name 并统计返回数量 b_count

    从 0 开始循环便利总数到 b_count 范围 [0,b_count]
    在当前目录下创建对应的 b_name 目录并进入目录，如果存在则不创建目录直接进入目录
    请求 b_url 链接，若为 200 且有内容则返回 b_content

    从 b_content 中 <nav class="my-2"></nav> 元素中获得 <div></div> 并从中获取 <span></span> 并从中获取倒数第二个元素 <a href=""></a> 属性中得到总页数(比如得到了 /?page=11 则返回总页数 11) b_pager ，如果没有获取到 则说明只有1页默认返回 1 即 b_pager=1

    从 1 开始循环便利总页数到 b_pager 范围 [1,b_pager+1]
    当为 1 则直接将 b_content 赋值给 a_b_pager_url_content
    当不为 1 则拼接 b_url 和 b_pager 得到拼接 a_b_pager_url 类似 https://fuligirl.top/albums/3702?page=11 的拼接，其中 https://fuligirl.top/albums/3702 是 b_url， ?page=2 代表第2页之后的拼接以此类推，并请求，若为 200 且有内容则返回 a_b_pager_url_content
    
    从 a_b_pager_url_content 中获取 <div class="pt-4"></div> 元素并从中匹配 <div class="my-1"></div> 并从中匹配全部的 <img class="block my-1" src="" title="" alt=""> 的图像资源并提取其中的src链接为 c_url 并统计总数量 c_count

    从 0 开始循环便利总数到 c_count 范围 [0,c_count]
    请求 c_url 链接 若为 200 且有内容则返回 c_content
    处理图片链接 c_url 并截取文件名得到 c_name ，检查文件路径中是否与 c_name 重名，如果找到重名文件则代表文件存在也就不用请求图片链接，如果找不到重名文件则说明文件不存在则请求图片链接并存储下载并截取文件名存储到 c_name 目录中，比如获取的链接为 https://telegraph-image.pages.dev/file/d9831eb87fbe154411dee.jpg 那么存储的文件名就为 d9831eb87fbe154411dee.jpg 并睡眠3s

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
BASE_URL = "https://fuligirl.top"
# 备用图片源——最近发现 https://telegraph-image.pages.dev/file 似乎不正常
TG_URL = "https://im.gurl.eu.org/file"
DEFAULT_TARGET_DIR = "美女图集"
DEFAULT_RETRY_MAX = 5
DEFAULT_PAGE_SLEEP = 10      # 每个分页处理完后的休眠秒数
DEFAULT_IMAGE_SLEEP = 3      # 每张图片下载后的休眠秒数
DEFAULT_CONCURRENCY = 4      # 并发处理专辑的数量

# ---------------------- 日志设置 ----------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---------------------- 辅助函数 ----------------------
def create_directory(path):
    """创建目录（如果不存在则创建），返回该目录绝对路径"""
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.abspath(path)

def sanitize_filename(filename):
    """使用正则过滤非法文件名字符"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def request_with_retry(session, url, max_retries=DEFAULT_RETRY_MAX):
    """
    通过 session 发送 GET 请求，内置重试机制与异常捕获
    若响应状态码为 200 且内容非空，则返回 response.content，否则返回 None
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url)
            if response.status_code == 200 and response.content:
                return response.content
            else:
                raise Exception(f"状态码: {response.status_code}")
        except Exception as e:
            logging.error("请求 [%s] 出错: %s (重试 %d/%d)", url, e, attempt, max_retries)
            time.sleep(random.uniform(2, 5))
    return None

def parse_total_pages_from_nav(soup):
    """
    从页面中 <nav class="my-2"></nav> 元素内提取总页数：
      逻辑：寻找 nav.my-2 -> div -> span -> 所有 a 标签，
      然后取倒数第二个 a 标签的 href 中提取页面参数（如 "/?page=308" 提取 308）
    """
    try:
        nav = soup.find('nav', class_='my-2')
        if nav:
            div = nav.find('div')
            if div:
                span = div.find('span')
                if span:
                    a_tags = span.find_all('a')
                    if a_tags and len(a_tags) >= 2:
                        return int(a_tags[-2]['href'].split('=')[-1])
    except Exception as e:
        logging.error("解析总页数失败: %s", e)
    return 1

# ---------------------- 专辑列表解析 ----------------------
def get_galleries_from_listing(listing_content):
    """
    从专辑列表页的 HTML 内容中解析出所有专辑信息
      - 按原脚本思路：在 <div class="my-1"></div> 中获取每个专辑的链接和标题
    返回一个列表，每项为 (gallery_url, gallery_title)
    """
    galleries = []
    soup = BeautifulSoup(listing_content, 'html.parser')
    # 使用 CSS 选择器，不包含额外空格的 div.my-1（原脚本写法）
    divs = soup.select('div.my-1:not([class*=" "])')
    if not divs:
        logging.warning("未找到任何专辑容器！")
        return galleries
    for div in divs:
        try:
            a_tag = div.find('a')
            h2_tag = div.find('h2', class_='font-semibold')
            if a_tag and h2_tag:
                gallery_url = urljoin(BASE_URL, a_tag['href'])
                gallery_title = sanitize_filename(h2_tag.get_text().strip())
                galleries.append((gallery_url, gallery_title))
        except Exception as e:
            logging.error("解析专辑信息出错: %s", e)
    return galleries

# ---------------------- 专辑图片下载处理 ----------------------
def process_gallery(session, gallery_url, gallery_title, target_dir,
                    retry=DEFAULT_RETRY_MAX, page_sleep=DEFAULT_PAGE_SLEEP, image_sleep=DEFAULT_IMAGE_SLEEP):
    """
    处理单个专辑的下载流程：
      1. 在目标目录下创建专辑文件夹；
      2. 请求专辑首页，解析出专辑总分页数（若解析失败默认为 1）；
      3. 遍历每一分页：
          - 页码 1 使用首页内容，其余构造 URL 如：gallery_url + "?page=2"
          - 解析出 <div class="pt-4"></div> 内的所有 <img class="block my-1"> 标签，提取 src
      4. 对于每个图片链接：
          - 若对应文件不存在则下载保存，下载后休眠 image_sleep 秒
      5. 完成一个分页后休眠 page_sleep 秒
    """
    logging.info("开始处理专辑: %s (%s)", gallery_title, gallery_url)
    gallery_dir = create_directory(os.path.join(target_dir, gallery_title))
    b_content = request_with_retry(session, gallery_url, max_retries=retry)
    if not b_content:
        logging.error("无法获取专辑内容: %s", gallery_url)
        return

    soup = BeautifulSoup(b_content, 'html.parser')
    total_gallery_pages = parse_total_pages_from_nav(soup)
    logging.info("专辑 [%s] 共 %d 页", gallery_title, total_gallery_pages)

    for page in range(1, total_gallery_pages + 1):
        if page == 1:
            page_url = gallery_url
            page_content = b_content
        else:
            page_url = gallery_url + "?page=" + str(page)
            page_content = request_with_retry(session, page_url, max_retries=retry)
            if not page_content:
                logging.error("获取专辑分页内容失败: %s", page_url)
                continue

        logging.info("处理专辑分页: %s", page_url)
        page_soup = BeautifulSoup(page_content, 'html.parser')
        pt4_div = page_soup.find('div', class_='pt-4')
        if not pt4_div:
            logging.warning("未找到图片容器 (div.pt-4) at %s", page_url)
            continue

        # 提取所有符合条件的图片链接
        img_tags = pt4_div.find_all('img', class_='block my-1')
        c_urls = [img['src'] for img in img_tags if img.get('src')]
        logging.info("在页面 [%s] 中共找到 %d 张图片", page_url, len(c_urls))
        for idx, c_url in enumerate(c_urls):
            filename = sanitize_filename(c_url.split('/')[-1])
            # 临时替换图片源
            c_url = f'{TG_URL}/{filename}'
            filepath = os.path.join(gallery_dir, filename)
            if os.path.exists(filepath):
                logging.info("图片已存在: %s", filepath)
                continue
            img_content = request_with_retry(session, c_url, max_retries=retry)
            if not img_content:
                logging.error("下载图片失败: %s", c_url)
                continue
            try:
                with open(filepath, 'wb') as f:
                    f.write(img_content)
                logging.info("下载成功 [%d/%d]: %s", idx + 1, len(c_urls), filepath)
            except Exception as e:
                logging.error("保存图片失败 [%s]: %s", filepath, e)
            time.sleep(image_sleep)
        logging.info("完成当前分页 [%s]，等待 %d 秒...", page_url, page_sleep)
        time.sleep(page_sleep)

# ---------------------- 专辑列表页处理 ----------------------
def process_listing_pages(session, main_content, target_dir):
    """
    处理专辑列表首页：
      1. 利用主页面解析出总页码；
      2. 遍历每个列表页，提取该页中的专辑信息 (gallery_url, gallery_title)
      3. 返回全部专辑信息列表
    """
    soup = BeautifulSoup(main_content, 'html.parser')
    total_pages = parse_total_pages_from_nav(soup)
    logging.info("主列表共 %d 页", total_pages)
    all_galleries = []
    for page in range(1, total_pages + 1):
        if page == 1:
            listing_url = BASE_URL
            page_content = main_content
        else:
            listing_url = BASE_URL + "/?page=" + str(page)
            page_content = request_with_retry(session, listing_url)
            if not page_content:
                logging.error("获取列表页失败: %s", listing_url)
                continue
        logging.info("处理列表页: %s", listing_url)
        galleries = get_galleries_from_listing(page_content)
        all_galleries.extend(galleries)
        logging.info("在列表页 [%s] 中共找到 %d 个专辑", listing_url, len(galleries))
        time.sleep(3)
    return all_galleries

# ---------------------- 主程序 ----------------------
def main():
    parser = argparse.ArgumentParser(description="Fuligirl 图集爬虫：爬取 fuligirl.top 中的图片资源")
    parser.add_argument('-d', '--dir', default=DEFAULT_TARGET_DIR, help=f"目标存储目录 (默认: {DEFAULT_TARGET_DIR})")
    parser.add_argument('-r', '--retries', type=int, default=DEFAULT_RETRY_MAX, help=f"请求重试次数 (默认: {DEFAULT_RETRY_MAX})")
    parser.add_argument('--page_sleep', type=float, default=DEFAULT_PAGE_SLEEP, help=f"分页处理后等待时间（秒，默认: {DEFAULT_PAGE_SLEEP}）")
    parser.add_argument('--image_sleep', type=float, default=DEFAULT_IMAGE_SLEEP, help=f"单张图片下载后等待时间（秒，默认: {DEFAULT_IMAGE_SLEEP}）")
    parser.add_argument('-c', '--concurrency', type=int, default=DEFAULT_CONCURRENCY, help=f"并发处理专辑数量 (默认: {DEFAULT_CONCURRENCY})")
    args = parser.parse_args()

    target_dir = create_directory(args.dir)
    logging.info("图片存储目录: %s", target_dir)

    # 建立全局 session 并设置浏览器请求头
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/85.0.4183.83 Safari/537.36")
    })

    # 请求主页面（专辑列表入口）
    main_url = BASE_URL
    main_content = request_with_retry(session, main_url, max_retries=args.retries)
    if not main_content:
        logging.error("无法获取主页面: %s", main_url)
        return

    galleries = process_listing_pages(session, main_content, target_dir)
    logging.info("共获取到 %d 个专辑信息", len(galleries))

    # 对所有专辑进行并发处理
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_dict = {
            executor.submit(process_gallery, session, gallery_url, gallery_title,
                            target_dir, args.retries, args.page_sleep, args.image_sleep): (gallery_url, gallery_title)
            for gallery_url, gallery_title in galleries
        }
        for future in as_completed(future_dict):
            gallery_info = future_dict[future]
            try:
                future.result()
            except Exception as e:
                logging.error("专辑 [%s] 处理异常: %s", gallery_info[1], e)

    session.close()
    logging.info("所有爬取任务完成！")

if __name__ == "__main__":
    main()
