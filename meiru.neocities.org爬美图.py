# 思路
'''
    在脚本所在目录下创建 美女图集 文件夹并进入文件夹，如果存在则忽略创建直接进入目录,创建重试函数，为了规避网络问题导致的 tls 报错，并且使用脚本实现需求

    定义 跳过链接集
    创建判断链接是在跳过链接集中存在，并返回布尔
    
    定义 a_url 为 https://meiru.neocities.org
    请求 a_url 若为 200 且有内容则返回 a_content

    从 a_content 中 <div id="pagination"></div> 的元素中获得最后一个 <div ></div> 的元素中获得最后一个 <div ></div> 的元素并从中获取倒数第二个 <a href="" class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium" one-link-mark="yes"></a> 元素并从 href 属性中得到总页数(比如得到了 https://meiru.neocities.org/page/226/ 则返回总页数 226) a_pager

    从 1 开始循环便利总页数到 a_pager 范围 [1,a_pager+1]
    当为 1 则拼接 a_url 对应的链接赋值给 a_pager_url ，将 a_content 赋值给 a_pager_url_content
    当不为1 则拼接 a_url + a_pager 得到类似 https://meiru.neocities.org/page/2/ 的拼接其中 /page/2/ 代表第2页之后的拼接以此类推，得到拼接 a_pager_url ，请求 a_pager_url 若为 200 且有内容则返回 a_pager_url_content
    
    从 a_pager_url_content 中 <div class="p-2"></div> 中匹配 <div class="text-sm text-gray-500 text-center"></div> 中匹配 <a href=""></a> 提取全部的链接 b_url 和对应链接名 b_name（废除项） 并统计返回数量 b_count

    从 0 开始循环便利总数到 b_count 范围 [0,b_count]
    在当前目录下创建对应的 b_name 目录并进入目录，如果存在则不创建目录直接进入目录（废除项）
    请求 b_url 对应的链接，若为 200 且有内容则返回 b_content

    从 b_content 中 <div id="pagination"></div> 的元素中获得最后一个 <div ></div> 的元素中获得最后一个 <div ></div> 的元素并从中获取倒数第二个 <a href="" class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium" one-link-mark="yes"></a> 元素并从 href 属性值中得到链接总页数(比如得到了 https://meiru.neocities.org/models/%E5%B9%B4%E5%B9%B4/page/226/ 则返回总页数 226) b_pager ，如果没有获取到 获取倒数第二个 <a href="" class="bg-white border-gray-300 text-gray-500 hover:bg-gray-50 relative inline-flex items-center px-4 py-2 border text-sm font-medium" one-link-mark="yes"></a>元素，则说明只有1页默认返回 1 即 b_pager=1 ，并提取链接（比如提取得到 https://meiru.neocities.org/models/%E5%B9%B4%E5%B9%B4/page/ ）返回 c_url

    从 1 开始循环便利总页数到 b_pager 范围 [1,b_pager+1]
    当为 1 则将 c_url 对应的链接赋值给 c_b_pager_url ，并将 b_content 赋值给 c_b_pager_url_content
    当不为 1 则拼接 c_url+b_pager 得到类似 https://meiru.neocities.org/models/%E5%B9%B4%E5%B9%B4/page/2/ 的拼接，其中 https://meiru.neocities.org/models/%E5%B9%B4%E5%B9%B4/page/ 是 c_url ，2/ 代表第2页之后的拼接以此类推，得到拼接 c_b_pager_url 并请求，若为 200 且有内容则返回 c_b_pager_url_content
    
    从 c_b_pager_url_content 中获取 <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-1 p-1"></div> 元素并从中匹配全部的 <div class="p-2"></div> 中匹配第一个 <div ></div> 元素并从中匹配  <a href=""></a> 的链接 d_url 并从中匹配 <img src="" alt="" class="rounded-lg shadow-sm w-full h-72 md:h-96 object-cover" > 的 alt 文件夹名 d_name 并统计总数量 d_count

    从 0 开始循环便利总数到 d_count 范围 [0,d_count]
    创建对应的 d_name 目录并进入目录，如果存在则不创建目录直接进入目录
    拼接 d_url 对应的链接并请求 若为 200 且有内容则返回 d_content

    从 d_content 中获取 <div id="gallery"></div> 元素并从中获取 <img src="" alt="" title="" class="block my-2 mx-auto" > 中匹配 src 获取全部图片链接 e_url ，并得到图片链接总数量 e_count
    
    从 0 开始循环便利总数到 e_count 范围 [0,e_count]
    处理图片链接 e_url 并截取文件名得到 e_name ，检查文件路径中是否与 e_name 重名，如果找到重名文件则代表文件存在也就不用请求图片链接，如果找不到重名文件则说明文件不存在则请求图片链接并存储下载并截取文件名存储到 d_name 目录中，比如获取的链接为 https://telegraph-image.pages.dev/file/dbcc75fbf6f8a11dccbad.jpg 那么存储的文件名就为 dbcc75fbf6f8a11dccbad.jpg 并睡眠3s

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
# 美图网
BASE_URL = "https://meiru.neocities.org"

# 原始图片源 https://teleimgs.netlib.re/file
# 备用图片源——最近发现 https://telegraph-image.pages.dev/file
# 备用图片源——最近发现 https://im.gurl.eu.org/file
TG_URL = "https://teleimgs.netlib.re/file"
DEFAULT_TARGET_DIR = "美女图集"
DEFAULT_RETRY_MAX = 5
#DEFAULT_PAGE_SLEEP = 10      # 每个分页处理后等待时间（秒）
DEFAULT_PAGE_SLEEP = 1      # 每个分页处理后等待时间（秒）
DEFAULT_IMAGE_SLEEP = 3      # 每张图片下载后等待时间（秒）
DEFAULT_CONCURRENCY = 4      # 并发处理专辑链接数量

# ---------------------- 跳过链接集 ----------------------
SKIP_URLS = {
    "https://meiru.neocities.org/view/aqua-kiara-sessyoin",
}

# ---------------------- 日志设置 ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------------------- 辅助函数 ----------------------
def create_directory(path):
    """创建目录（如果不存在则创建），返回绝对路径。"""
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.abspath(path)

def sanitize_filename(filename):
    """过滤掉文件名中的非法字符。"""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def request_with_retry(session, url, max_retries=DEFAULT_RETRY_MAX):
    """
    使用传入的 session 发送 GET 请求，内置重试机制。
    若响应状态码为200且有内容，则返回 response.content，否则返回 None。
    """
    for attempt in range(1, max_retries+1):
        try:
            response = session.get(url, timeout=10)
            if response.status_code == 200 and response.content:
                return response.content
            else:
                raise Exception(f"Status code: {response.status_code}")
        except Exception as e:
            logging.error("请求 [%s] 出错: %s (重试 %d/%d)", url, e, attempt, max_retries)
            time.sleep(random.uniform(2, 5))
    return None

def check_url_exists(test_url):
    """判断给定链接是否在跳过链接集中。"""
    return test_url in SKIP_URLS

def parse_pagination(soup, base_url=None):
    """
    更鲁棒地解析分页：
    - 在 div#pagination 下找到所有有 href 的 <a>
    - 尝试从 <a> 的文本或 href 中提取页码，取最大值作为总页数
    - 计算出一个 base_pag_url（可用于拼接后续分页）
    返回 (total_pages:int, base_pag_url:str|None)
    """
    try:
        pager_links = soup.select("div#pagination a[href]")
        if not pager_links:
            return 1, None

        page_numbers = set()
        last_href = None
        for a in pager_links:
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            # 优先用可转 int 的文本
            if text.isdigit():
                page_numbers.add(int(text))
                last_href = href
                continue
            # 否则尝试从 href 中提取 page/123 或 ?page=123
            m = re.search(r'page[=/](\d+)', href)
            if m:
                page_numbers.add(int(m.group(1)))
                last_href = href

        if not page_numbers:
            return 1, None

        total_pages = max(page_numbers)

        # 规范化 last_href 为绝对地址（若提供了 base_url）
        if base_url and last_href:
            last_href = urljoin(base_url, last_href)

        base_pag_url = None
        if last_href:
            # 处理 ?page=123 的情况 -> 保留 ?page= 前缀
            if '?page=' in last_href:
                idx = last_href.find('?page=')
                base_pag_url = last_href[:idx + len('?page=')]
            else:
                # 处理 /page/123/ 的情况 -> 保留到 '/page/'
                m2 = re.search(r'(.*/page/)', last_href)
                if m2:
                    base_pag_url = m2.group(1)
                else:
                    # 最后兜底：取 last_href 的目录部分
                    parsed = urlparse(last_href)
                    path = parsed.path
                    base_pag_url = urljoin(last_href, '../')

        return int(total_pages), base_pag_url
    except Exception as e:
        logging.error("解析分页出错: %s", e)
        return 1, None

def get_gallery_links(page_content):
    """
    从列表页 HTML 中提取所有专辑链接。
    目标：在 <div class="p-2"></div> 内部找到 <div class="text-sm text-gray-500 text-center"> 下的 <a href=""> 链接集合，
    并返回每个专辑的绝对链接。
    改为：提取 <div class="text-center font-semibold"> 里的 <a>
    """
    soup = BeautifulSoup(page_content, "html.parser")
    links = soup.select('div.text-center.font-semibold a[href]')
    gallery_urls = [urljoin(BASE_URL, link['href']) for link in links]
    return gallery_urls
def process_gallery(session, b_url, retry, page_sleep, image_sleep, output_dir):
    """
    处理单个专辑（b_url）的下载流程：
      1. 请求 b_url 获取专辑首页内容。
      2. 解析分页信息，得到专辑总页数（b_pager）及详情链接的基准链接（c_url）。
      3. 遍历专辑内分页：第一页直接使用；其它分页构造 URL：c_url + '/{page}/'
      4. 对每个分页中，通过选择器提取详情条目（d_url 与 d_name），并对每个详情页下载其中图片。
    """
    logging.info("开始处理专辑: %s", b_url)
    b_content = request_with_retry(session, b_url, max_retries=retry)
    if not b_content:
        logging.error("无法获取专辑内容: %s", b_url)
        return

    b_soup = BeautifulSoup(b_content, "html.parser")
    b_pager, c_url = parse_pagination(b_soup)
    logging.info("专辑 [%s] 总分页数: %d", b_url, b_pager)
    if c_url is None:
        c_url = b_url

    for k in range(1, b_pager + 1):
        if k == 1:
            c_b_pager_url = c_url  # 第一页直接使用基准链接
            c_b_pager_content = b_content
        else:
            c_b_pager_url = c_url.rstrip('/') + '/' + str(k) + '/'
            c_b_pager_content = request_with_retry(session, c_b_pager_url, max_retries=retry)
            if not c_b_pager_content:
                logging.error("获取专辑分页失败: %s", c_b_pager_url)
                continue

        logging.info("处理专辑内第 %d 页: %s", k, c_b_pager_url)
        c_soup = BeautifulSoup(c_b_pager_content, "html.parser")
        # 从每个分页中提取详情条目：选择器 'div.p-2 div:first-child a[href]'
        # 直接选详情页入口 <div class="text-center font-semibold"> 里的 a
        a_tags = c_soup.select("div.text-center.font-semibold a[href]")
        d_urls = [a.get("href") for a in a_tags]
        d_names = [a.get_text(strip=True) for a in a_tags]

        d_count = len(d_urls)
        logging.info("专辑内第 %d 页中共找到 %d 个详情条目", k, d_count)

        for l in range(d_count):
            d_url = d_urls[l]
            # 将详情链接转换为绝对链接
            d_url = urljoin(b_url, d_url)
            d_folder_name = sanitize_filename(d_names[l])
            folder_path = create_directory(os.path.join(output_dir, d_folder_name))
            logging.info("处理详情 [%s] - %s", d_folder_name, d_url)
            if check_url_exists(d_url):
                logging.info("链接在跳过列表中，跳过: %s", d_url)
                continue

            d_content = request_with_retry(session, d_url, max_retries=retry)
            if not d_content:
                logging.error("无法获取详情页: %s", d_url)
                continue

            d_soup = BeautifulSoup(d_content, "html.parser")
            gallery_div = d_soup.find("div", id="gallery")
            if not gallery_div:
                logging.warning("详情页中未找到图片容器: %s", d_url)
                continue

            e_imgs = gallery_div.select("img.block.my-2.mx-auto")
            e_urls = [img.get("src") for img in e_imgs if img.get("src")]
            e_count = len(e_urls)
            logging.info("详情页共找到 %d 张图片", e_count)

            for m in range(e_count):
                e_url = e_urls[m]
                # 将图片链接转换为绝对链接
                e_url = urljoin(BASE_URL, e_url)
                # 替换 .jpg 为 .png ?
                e_name = e_url.split("/")[-1].replace('.jpg','.png')
                # 临时替换图片源
                e_url = f'{TG_URL}/{e_name}'
                e_path = os.path.join(folder_path, e_name)
                if os.path.exists(e_path):
                    logging.info("图片已存在: %s", e_path)
                    continue
                logging.info("下载图片 %d/%d: %s -> %s", m+1, e_count, e_url, e_path)
                e_content = request_with_retry(session, e_url, max_retries=retry)
                if not e_content:
                    logging.error("下载图片失败: %s", e_url)
                    continue
                try:
                    with open(e_path, "wb") as f:
                        f.write(e_content)
                except Exception as e:
                    logging.error("保存图片 %s 失败: %s", e_path, e)
                time.sleep(image_sleep)
        logging.info("专辑内第 %d 页处理完毕，等待 %d 秒...", k, page_sleep)
        time.sleep(page_sleep)
def process_home_page(session, base_url, retry=DEFAULT_RETRY_MAX):
    """
    使用 parse_pagination 得到总页数与 base_pag_url，返回所有列表页完整 URL 列表。
    """
    a_content = request_with_retry(session, base_url, max_retries=retry)
    if not a_content:
        logging.error("无法获取主页: %s", base_url)
        return []

    a_soup = BeautifulSoup(a_content, "html.parser")
    total_pages, base_pag_url = parse_pagination(a_soup, base_url=base_url)
    logging.info("主页总分页数: %d, base_pag_url: %s", total_pages, base_pag_url)

    home_pages = []
    # 若检测到 base_pag_url（/page/ 或 ?page=），用它拼接；否则回退到 base_url + '/page/X/'
    if base_pag_url:
        for i in range(1, total_pages + 1):
            if i == 1:
                home_pages.append(base_url)
            else:
                # base_pag_url 里可能已包含完整前缀，使用 urljoin 来保证安全
                home_pages.append(urljoin(base_pag_url, str(i) + '/'))
    else:
        for i in range(1, total_pages + 1):
            if i == 1:
                home_pages.append(base_url)
            else:
                home_pages.append(base_url.rstrip('/') + '/page/' + str(i) + '/')

    # 去重并保持顺序（防止重复链接）
    seen = set()
    unique_pages = []
    for p in home_pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)

    return unique_pages

def process_listing_page(session, page_url):
    """
    处理列表页，提取所有专辑链接（gallery URL），返回完整链接列表。
    """
    content = request_with_retry(session, page_url, max_retries=DEFAULT_RETRY_MAX)
    if not content:
        logging.error("无法获取列表页: %s", page_url)
        return []
    soup = BeautifulSoup(content, "html.parser")
    gallery_urls = get_gallery_links(content)
    logging.info("列表页 [%s] 共获取 %d 个专辑链接", page_url, len(gallery_urls))
    return gallery_urls

def main():
    parser = argparse.ArgumentParser(
        description="美女图集爬虫：爬取 meiru.neocities.org 网站的图片资源"
    )
    parser.add_argument('-d', '--dir', default=DEFAULT_TARGET_DIR,
                        help=f"目标存储目录 (默认: {DEFAULT_TARGET_DIR})")
    parser.add_argument('-r', '--retries', type=int, default=DEFAULT_RETRY_MAX,
                        help=f"请求重试次数 (默认: {DEFAULT_RETRY_MAX})")
    parser.add_argument('--page_sleep', type=float, default=DEFAULT_PAGE_SLEEP,
                        help=f"每个分页处理后等待时间（秒，默认: {DEFAULT_PAGE_SLEEP}）")
    parser.add_argument('--image_sleep', type=float, default=DEFAULT_IMAGE_SLEEP,
                        help=f"单张图片下载后等待时间（秒，默认: {DEFAULT_IMAGE_SLEEP}）")
    parser.add_argument('-c', '--concurrency', type=int, default=DEFAULT_CONCURRENCY,
                        help=f"并发处理专辑链接数量 (默认: {DEFAULT_CONCURRENCY})")
    args = parser.parse_args()

    output_dir = create_directory(args.dir)
    logging.info("图片存储目录: %s", output_dir)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/85.0.4183.83 Safari/537.36"
    })

    os.chdir(output_dir)
    logging.info("当前工作目录: %s", os.path.abspath('.'))

    # 获取所有列表页的 URL
    home_pages = process_home_page(session, BASE_URL, retry=args.retries)
    all_galleries = []
    for page_url in home_pages:
        galleries = process_listing_page(session, page_url)
        all_galleries.extend(galleries)
        time.sleep(3)
    logging.info("共获得 %d 个专辑链接", len(all_galleries))

    # 对所有专辑链接进行并发处理
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_to_gallery = {
            executor.submit(process_gallery, session, gallery_url, args.retries, args.page_sleep, args.image_sleep, output_dir): gallery_url
            for gallery_url in all_galleries
        }
        for future in as_completed(future_to_gallery):
            gallery_url = future_to_gallery[future]
            try:
                future.result()
            except Exception as e:
                logging.error("处理专辑 [%s] 时发生异常: %s", gallery_url, e)
    session.close()
    logging.info("所有爬取任务完成！")

if __name__ == "__main__":
    main()
