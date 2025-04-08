# 思路
'''
    在脚本所在目录下创建 美女图集 文件夹，存在则忽略，并进入文件夹,创建重试函数，为了规避网络问题导致的 tls 报错，并且使用脚本实现需求
    
    定义 url 为 https://www.24fa.com/
    拼接 url 和 c49.aspx 得到 a_url
    请求 a_url 若为 200 且有内容则返回 a_content
    
    从 a_content 中的 <div class="pager"></div> 中获得 倒数第3个<li></li> 元素并获取文本值为总页数 a_pager

    从 1 开始循环便利总页数到 a_pager 范围 [1,a_pager+1]
    当为 1 则直接使用 a_content 赋值给 a_pager_content
    当不为 1 则处理 a_url 将结尾类似 c49.aspx 的部分中 .aspx 去掉，得到 a_url_cut 用于后续拼接 
    拼接 a_url_cut 和 a_pager 得到类似 https://www.24fa.com/c49p2.aspx 的拼接其中 p2 代表第一页之后的拼接以此类推，得到拼接 a_url_pager
    请求 a_url_pager 若为 200 且有内容则返回 a_pager_content

    从 a_pager_content 中的 <div class="mx"></div> 中匹配获得以下两个内容，并统计总数量 b_count
        n 开头 .aspx 结尾的全部文本 b_text
        标题 b_title
    在当前目录下创建 b_title 目录，存在则忽略，并进入目录
    
    从 0 开始循环便利总页数到 b_count 范围 [0,b_count]
    拼接 url 和 b_text 中的每一个文本得到 b_url
    请求 b_url 若为 200 且有内容则返回 b_content
    从 b_content 中的 <div class="pager"></div> 中获得倒数第3个 <li></li> 元素获取文本值总页数 b_pager

    从 1 开始循环便利总页数到 c_pb_pagerager 范围 [1,b_pager]
    当为 1 则直接使用 b_content 赋值给 b_pager_content
    当不为 1 则处理 b_url 将结尾类似 n106083c49.aspx 的部分中 .aspx 去掉的到 b_url_cut 用于后续拼接 
    拼接 b_url_cut 和 b_count 得到类似 https://www.24fa.com/n106083c49p1.aspx 的拼接其中 p1 代表第一页之后的拼接以此类推，得到拼接 b_url_pager
    请求 b_url_pager  若为 200 且有内容则返回 b_pager_content
    从 b_pager_content 中的 <div id="content"></div></div> 中匹配获得 upload 开头 .jpg_gzip.aspx 结尾的全部文本 c_text 并统计数量 c_count
    
    从 0 开始循环遍历总页数到 c_count 范围 [0,c_count]
    处理 c_text 的每一个文本只截取类似 24011909415963.jpg_gzip.aspx 的部分并且替换 .jpg_gzip.aspx 为 .jpg 作为文件名 filename
    
    拼接 url 和 c_text 得到 c_url
    如果存在则跳过，不存在则请求 c_url 获取图片并保存到 b_title 目录，并命名为 filename 休息3s
    每次结束一个目录循环休息10s
    
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
BASE_URL = "https://www.24fa.com/"
DEFAULT_TARGET_DIR = "美女图集"
DEFAULT_RETRY_MAX = 5
DEFAULT_IMG_SLEEP = 3       # 每张图片下载后的休息秒数
DEFAULT_PAGE_SLEEP = 10     # 每个分页结束后的等待秒数
DEFAULT_CONCURRENCY = 4     # 默认并发爬取专辑数

# ---------------------- 日志配置 ----------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ---------------------- 辅助函数 ----------------------
def create_directory(path):
    """创建目录（如果不存在的话），返回绝对路径。"""
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.abspath(path)

def sanitize_filename(filename):
    """使用正则过滤非法文件名字符。"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def request_with_retry(session, url, max_retries=DEFAULT_RETRY_MAX):
    """
    通过传入 session 发送 GET 请求，内置重试机制与异常捕获。
    若响应状态码为200且内容非空，则返回 response.content，否则返回 None。
    当响应文本中存在 "window.location.href" 说明可能存在重定向或异常，也会重试。
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url)
            if response.status_code == 200 and response.content:
                if "window.location.href" in response.text:
                    raise Exception("检测到重定向提示")
                return response.content
            else:
                raise Exception(f"状态码: {response.status_code}")
        except Exception as e:
            logging.error("请求 [%s] 出错: %s (重试 %d/%d)", url, e, attempt, max_retries)
            time.sleep(random.uniform(2, 5))
    return None

def parse_total_pages(soup, container_class='pager'):
    """
    从传入的 soup 对象中查找指定容器（默认 class='pager'）
    内的倒数第三个 <li> 元素，并取其文本作为总页数；解析异常时默认为1。
    """
    pager_div = soup.find('div', class_=container_class)
    if pager_div:
        lis = pager_div.find_all('li')
        try:
            return int(lis[-3].get_text())
        except (IndexError, ValueError):
            logging.error("解析总页数失败。")
    return 1

# ---------------------- 专辑页面与图片下载处理 ----------------------
def process_album_page(session, album_url, album_dir, 
                       img_sleep=DEFAULT_IMG_SLEEP, page_sleep=DEFAULT_PAGE_SLEEP):
    """
    处理单个专辑的下载流程：
      1. 请求专辑首页，并解析出总分页数；
      2. 遍历专辑每一分页，获取 <div id="content"> 中的图片链接（只匹配以 upload/ 开头且以 .jpg_gzip.aspx 结尾的部分）；
      3. 对每个图片链接构造文件名（将 .jpg_gzip.aspx 替换为 .jpg），若该文件尚未下载，则下载并保存到 album_dir 中；
      4. 每下载完一个分页后休眠一定时间，缓解请求频率。
    """
    first_page_content = request_with_retry(session, album_url)
    if not first_page_content:
        logging.error("获取专辑首页失败：%s", album_url)
        return

    album_soup = BeautifulSoup(first_page_content, 'html.parser')
    total_pages = parse_total_pages(album_soup)  # 专辑图片的分页
    logging.info("专辑 [%s] 总分页数：%d", album_url, total_pages)

    for p in range(1, total_pages + 1):
        if p == 1:
            page_url = album_url
            page_content = first_page_content
        else:
            url_cut = album_url.rsplit('.', 1)[0]
            page_url = f"{url_cut}p{p}.aspx"
            page_content = request_with_retry(session, page_url)
            if not page_content:
                logging.error("获取专辑分页失败：%s", page_url)
                continue

        logging.info("处理专辑分页：%s", page_url)
        page_soup = BeautifulSoup(page_content, 'html.parser')
        content_div = page_soup.find('div', id='content')
        if not content_div:
            logging.error("找不到图片所在的 div#content：%s", page_url)
            continue

        # 查找所有符合条件的图片链接
        img_elements = content_div.find_all('img')
        img_srcs = [img.get('src') for img in img_elements 
                    if img.get('src', '').startswith('upload/') and img.get('src', '').endswith('.jpg_gzip.aspx')]
        logging.info("页面 %s 找到 %d 张图片", page_url, len(img_srcs))
        for idx, src in enumerate(img_srcs):
            filename = sanitize_filename(src.split('/')[-1].replace(".jpg_gzip.aspx", ".jpg"))
            filepath = os.path.join(album_dir, filename)
            if os.path.exists(filepath):
                logging.info("图片已存在：%s", filepath)
                continue
            img_url = urljoin(BASE_URL, src)
            img_content = request_with_retry(session, img_url)
            if not img_content:
                logging.error("下载图片失败：%s", img_url)
                continue
            try:
                with open(filepath, 'wb') as f:
                    f.write(img_content)
                logging.info("下载成功：第%d张图片 %s，存储于 %s", idx + 1, img_url, filepath)
            except Exception as e:
                logging.error("保存图片 [%s] 错误：%s", filepath, e)
            # 下载完一张图片后稍等，防止请求过快
            time.sleep(img_sleep)
        logging.info("完成分页 [%s]，等待 %d 秒...", page_url, page_sleep)
        time.sleep(page_sleep)

def get_albums_from_listing_page(session, list_page_url):
    """
    从专辑列表页中解析出各专辑的信息
      返回一个列表，每个元素为元组 (album_url, album_title)
    """
    logging.info("处理专辑列表页：%s", list_page_url)
    page_content = request_with_retry(session, list_page_url)
    if not page_content:
        logging.error("获取列表页失败：%s", list_page_url)
        return []
    
    soup = BeautifulSoup(page_content, 'html.parser')
    total_pages = parse_total_pages(soup)
    logging.info("列表页 [%s] 总分页数：%d", list_page_url, total_pages)
    
    mx_div = soup.find('div', class_='mx')
    if not mx_div:
        logging.error("找不到专辑容器 <div class='mx'>")
        return []
    
    album_links = [a['href'] for a in mx_div.find_all('a')
                   if a.get('href', '').startswith('n') and a['href'].endswith('.aspx')]
    album_titles = [h5.get_text().strip() for h5 in mx_div.find_all('h5') if h5.get_text()]
    
    albums = []
    for idx, link in enumerate(album_links):
        title = album_titles[idx] if idx < len(album_titles) and album_titles[idx] else f"album_{idx}"
        title = sanitize_filename(title.replace(" ", "-"))
        album_url = urljoin(BASE_URL, link)
        albums.append((album_url, title))
    return albums

def process_album(album_info, target_dir, session, img_sleep, page_sleep):
    """
    根据 album_info（album_url, album_title），在目标目录下创建专辑文件夹，
    并调用 process_album_page 下载该专辑的所有图片。
    """
    album_url, album_title = album_info
    album_dir = create_directory(os.path.join(target_dir, album_title))
    logging.info("开始处理专辑 [%s]（%s）", album_title, album_url)
    process_album_page(session, album_url, album_dir, img_sleep=img_sleep, page_sleep=page_sleep)
    logging.info("完成专辑 [%s]", album_title)

# ---------------------- 主程序 ----------------------
def main():
    parser = argparse.ArgumentParser(description="美女图集爬虫：爬取 24fa.com 的图集")
    parser.add_argument('-d', '--dir', default=DEFAULT_TARGET_DIR, help=f"目标目录（默认: {DEFAULT_TARGET_DIR}）")
    parser.add_argument('-r', '--retries', type=int, default=DEFAULT_RETRY_MAX, help=f"请求重试次数（默认: {DEFAULT_RETRY_MAX}）")
    parser.add_argument('--img_sleep', type=float, default=DEFAULT_IMG_SLEEP, help=f"每张图片下载后等待时间（秒，默认: {DEFAULT_IMG_SLEEP}）")
    parser.add_argument('--page_sleep', type=float, default=DEFAULT_PAGE_SLEEP, help=f"每个专辑分页结束后等待时间（秒，默认: {DEFAULT_PAGE_SLEEP}）")
    parser.add_argument('-c', '--concurrency', type=int, default=DEFAULT_CONCURRENCY, help=f"并发爬取专辑数量（默认: {DEFAULT_CONCURRENCY}）")
    args = parser.parse_args()

    target_dir = create_directory(args.dir)
    logging.info("项目存储目录：%s", target_dir)

    # 建立全局 session 并设置请求头模拟浏览器
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/85.0.4183.83 Safari/537.36")
    })
    
    # 获取专辑列表首页（从 c49.aspx 开始）
    main_url = urljoin(BASE_URL, "c49.aspx")
    main_content = request_with_retry(session, main_url, max_retries=args.retries)
    if not main_content:
        logging.error("无法打开主页面：%s", main_url)
        return

    main_soup = BeautifulSoup(main_content, 'html.parser')
    total_list_pages = parse_total_pages(main_soup)
    logging.info("专辑列表主页面 [%s] 总分页数：%d", main_url, total_list_pages)
    
    # 收集所有专辑信息（多个列表页）
    album_infos = []
    for p in range(1, total_list_pages + 1):
        if p == 1:
            list_page_url = main_url
        else:
            url_cut = main_url.rsplit('.', 1)[0]
            list_page_url = f"{url_cut}p{p}.aspx"
        albums = get_albums_from_listing_page(session, list_page_url)
        album_infos.extend(albums)

    logging.info("共获取到 %d 个专辑信息", len(album_infos))
    
    # 使用线程池对专辑并发下载
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_to_album = {
            executor.submit(process_album, album_info, target_dir, session, args.img_sleep, args.page_sleep): album_info
            for album_info in album_infos
        }
        for future in as_completed(future_to_album):
            album_info = future_to_album[future]
            try:
                future.result()
            except Exception as e:
                logging.error("专辑 [%s] 下载异常：%s", album_info[1], e)
    
    session.close()
    logging.info("全部专辑下载完毕。")

if __name__ == "__main__":
    main()

