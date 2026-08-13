"""meirentu.cc 图集源（原 xrw 项目 scrape.py 移植）。

流程：从 index/11.html 往前爬（页内从最底往上）→ 抓图集原图 → pixhost 上传 →
每频道独立 Telegraph 页面（max_images / vip_link 差异化）→ 封面发对应频道。
标题自动清洗：去掉 [秀人付费]、.B011、[]88P 等多余字符，保留 秀人番外。
状态：state/meirentu_seen.json + state/meirentu_page.txt
"""
import os
import re
import sys
import time

from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings()

from core import ai as ai_core
from core import config as cfg
from core import images as img_core
from core import network
from core import state as state_core
from core import telegraph as tg_core
from core import telegram as tg_send
from core import uploader as up_core
from .base import register

# ── 环境变量 ──────────────────────────────────────────────
TOKEN = cfg.getenv("TG_TOKEN")
TELEGRAPH_TOKEN = cfg.getenv("TELEGRAPH_TOKEN")
# AI 打标签：优先 AI_API_KEY（DeepSeek，与 eh/4khd 共用）；未配置时复用 eh 的 AGNES_API_KEY
AI_API_KEY = cfg.getenv("AI_API_KEY") or cfg.getenv("AGNES_API_KEY")
AI_BASE_URL = cfg.getenv("AI_BASE_URL")
if not AI_BASE_URL:
    if cfg.getenv("AI_API_KEY"):
        AI_BASE_URL = "https://api.deepseek.com"
    else:
        AI_BASE_URL = cfg.getenv("AGNES_BASE_URL") or "https://apihub.agnes-ai.com/v1"
AI_BASE_URL = AI_BASE_URL.rstrip("/")
AI_MODEL = (cfg.getenv("AI_MODEL") or cfg.getenv("AGNES_MODEL")
            or ("deepseek-chat" if cfg.getenv("AI_API_KEY") else "agnes-2.0-flash"))
DEFAULT_VIP_LINK = cfg.getenv("VIP_LINK") or "https://t.me/xiuren88bot?start=buy_487"

ALBUMS_PER_DAY = int(cfg.getenv("ALBUMS_PER_DAY", "6"))
START_PAGE = int(cfg.getenv("START_PAGE", "11"))
MIN_PAGE = 1

# ── 常量 ──────────────────────────────────────────────────
BASE_URL = "https://meirentu.cc"
LIST_URL = BASE_URL + "/index/{page}.html"
TG_INTERVAL = 5      # 每套图集处理完后的休息秒数
UPLOAD_INTERVAL = int(cfg.getenv("PIXHOST_INTERVAL", "1"))  # 每张图片上传间隔（秒），默认 3s

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SESSION = network.new_session(HEADERS)
SESSION.verify = False


def load_channels():
    channels = cfg.load_channels("meirentu")
    for ch in channels:
        # "${VIP_LINK}" 未设置 → 用全局默认引导链接；显式 "" = 不引导
        if ch["vip_link"] is None:
            ch["vip_link"] = DEFAULT_VIP_LINK
    return channels


def clean_title(title):
    """去掉 [秀人付费]、.B011/No.N002、[]88P 等多余字符，保留 秀人番外 等有效分类词。"""
    t = title or ""
    # 去掉 [xxx] 括号标签（含空括号 []，如 [秀人付费] / [XiuRen 秀人] / [128P]）
    t = re.sub(r"\[[^\]]*\]", "", t)
    # 去掉 .B011 / No.N002 这类系列编号
    t = re.sub(r"(?:\bNo\.?\s*|\.\s*)[A-Za-z]\d{2,4}\b", "", t)
    # 去掉末尾页数标记（88P / 79P）
    t = re.sub(r"\s*\d+\s*P\s*$", "", t, flags=re.IGNORECASE)
    # 压缩空白并去掉首尾多余分隔符
    return re.sub(r"\s+", " ", t).strip(" .-·")


def generate_tags(title):
    """DeepSeek 生成 3-5 个中文标签；未配置/失败返回空串。"""
    if not AI_API_KEY or not title:
        return ""
    prompt = (
        "你是秀人写真标题标签专家。根据下面的写真标题，生成 3-5 个最贴切的标签。\n"
        "要求：\n"
        "1. 标签用中文，每个以 # 开头\n"
        "2. 优先提取：模特名、主题/场景（如 浴室、泡泡浴、校园）、服装/风格（如 丝袜、制服、泳装）\n"
        "3. 只输出标签，用空格分隔，不要任何解释、冒号或引号\n\n"
        f"标题：{title}\n\n"
        "示例输出：#潘思沁 #浴室 #泡泡浴 #主题写真"
    )
    content = ai_core.ask_chat(
        AI_BASE_URL, AI_API_KEY, AI_MODEL, "",
        prompt, max_tokens=100, temperature=0.3, attempts=1,
    )
    if not content:
        return ""
    tags = re.findall(r"#[\w一-鿿\-_]+", content)
    if not tags:
        tags = re.findall(r"[\w一-鿿]{2,8}", content)
        tags = [f"#{t}" for t in tags]
    return " ".join(list(dict.fromkeys(tags))[:5])


def fix_url(src):
    if not src:
        return None
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return BASE_URL + src
    return src


# ==================== 列表页 ====================

def get_albums_from_list(page):
    url = LIST_URL.format(page=page)
    print(f"📄 列表页: {url}")
    r = network.safe_get(SESSION, url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")

    albums = []
    seen_ids = set()
    for li in soup.select("li.i_list"):
        a = li.find("a", href=re.compile(r"/pic/(\d+)\.html"))
        if not a:
            continue
        m = re.search(r"/pic/(\d+)\.html", a["href"])
        if not m:
            continue
        album_id = m.group(1)
        if album_id in seen_ids:
            continue
        seen_ids.add(album_id)

        title = ""
        t = li.select_one(".meta-title")
        if t:
            title = clean_title(t.get_text(strip=True))
        date = ""
        d = li.select_one(".meta-post span")
        if d:
            date = d.get_text(strip=True)

        albums.append({
            "album_id": album_id,
            "url": f"{BASE_URL}/pic/{album_id}.html",
            "title": title,
            "date": date,
        })

    print(f"  找到 {len(albums)} 套图集")
    return albums


# ==================== 图集详情 + 原图链接 ====================

def collect_images(soup):
    """收集详情页正文区的图片直链"""
    urls = []
    for img in soup.select("div.content_left img"):
        src = img.get("src") or ""
        if "/mmdb.cc/file/" in src:
            urls.append(src)
    if not urls:
        for img in soup.select("img[src*='mmdb.cc/file/']"):
            urls.append(img.get("src"))
    return urls


def parse_album(album):
    """抓取图集全部页面，返回 (图片直链列表, 标题)"""
    album_id = album["album_id"]
    title = album.get("title", "")

    r = network.safe_get(SESSION, album["url"])
    if not r:
        return [], title
    soup = BeautifulSoup(r.text, "html.parser")

    h1 = soup.find("h1")
    if h1:
        title = clean_title(h1.get_text(strip=True)) or title

    urls = collect_images(soup)
    page_num = 1
    max_pages = 300
    while page_num < max_pages:
        next_href = None
        for a in soup.select("div.page a[href]"):
            txt = a.get_text(strip=True)
            if txt in ("下页", "下一页"):
                next_href = a["href"]
                break
        if not next_href:
            break
        page_url = fix_url(next_href)
        print(f"  📂 分页 {page_num + 1}: {page_url}")
        r2 = network.safe_get(SESSION, page_url)
        if not r2:
            break
        soup = BeautifulSoup(r2.text, "html.parser")
        urls.extend(collect_images(soup))
        page_num += 1
        time.sleep(0.5)

    # 去重保序
    dedup = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup, title


# ==================== 下载 / 上传 / Telegraph / 发送 ====================

def process_album(album, seen, state, channels, dry_run, limit_mode=False):
    """处理一套图集，成功返回 True，失败返回 False"""
    print(f"\n{'='*55}")
    print(f"处理图集: {album['url']}")

    image_urls, title = parse_album(album)
    if not title:
        title = album.get("title") or "无标题"
    print(f"  📝 标题: {title}")

    if not image_urls:
        print("  ⚠️ 无图片，跳过")
        if not dry_run:
            seen.add(album["album_id"])
            state.save(seen)
        return False

    print(f"  🖼️ 原图 {len(image_urls)} 张")

    if dry_run:
        for ch in channels:
            n = ch["max_images"]
            count = len(image_urls) if n == 0 else min(len(image_urls), n)
            vip_desc = "带会员引导" if ch["vip_link"] else "无引导"
            print(f"  [dry-run] 频道 {ch['chat_id']}: {count} 张（{vip_desc}）")
        return True

    tag_str = generate_tags(title)
    if tag_str:
        print(f"  🏷️ 标签: {tag_str}")

    # 下载封面（第一张图）
    print("  📥 下载封面...")
    cover_data, cover_type = img_core.download_image(SESSION, image_urls[0], referer=album["url"])
    if not cover_data:
        print("  ⚠️ 封面下载失败，跳过该图集")
        return False

    # 上传所有图片至 pixhost
    print(f"  ☁️ 上传 {len(image_urls)} 张图片到 pixhost...")
    pixhost_urls = []
    for i, u in enumerate(image_urls):
        data, ctype = img_core.download_image(SESSION, u, referer=album["url"])
        if not data:
            print(f"    [{i+1}/{len(image_urls)}] 下载失败，跳过")
            continue
        img_url = up_core.upload_pixhost(data.getvalue())
        if img_url:
            pixhost_urls.append(img_url)
            print(f"    [{i+1}/{len(image_urls)}] 上传成功")
        else:
            print(f"    [{i+1}/{len(image_urls)}] 上传失败，跳过")
        time.sleep(UPLOAD_INTERVAL)

    if not pixhost_urls:
        print("  ❌ 所有图片上传失败，跳过该图集")
        return False

    # 每个频道独立生成 Telegraph 页面并发送（图片只上传一次）
    sent_any = False
    for ch in channels:
        n = ch["max_images"]
        urls = pixhost_urls if n == 0 else pixhost_urls[:n]
        vip_desc = "带会员引导" if ch["vip_link"] else "无引导"
        print(f"  📝 频道 {ch['chat_id']}: 创建 Telegraph 页面（{len(urls)} 张，{vip_desc}）...")
        telegraph_url = tg_core.create_page(
            TELEGRAPH_TOKEN, title, urls,
            author_name="XiuRen Bot", footer="vip", vip_link=ch["vip_link"],
        )
        if not telegraph_url:
            print(f"  ❌ 频道 {ch['chat_id']} 页面创建失败，跳过")
            continue
        print(f"  ✅ 页面: {telegraph_url}")

        caption_head = f"{title}\n{tag_str}" if tag_str else title
        caption = f"{caption_head}\n\n<a href=\"{telegraph_url}\">👉 点击观看图集</a>"
        print(f"  📸 发送封面到频道 {ch['chat_id']}...")
        tg_send.send_photo(TOKEN, ch["chat_id"], cover_data, cover_type, caption)
        sent_any = True

    if not sent_any:
        print("  ❌ 所有频道发送失败，该图集不标记已处理，明天重试")
        return False

    seen.add(album["album_id"])
    state.save(seen)
    time.sleep(TG_INTERVAL)
    return True


# ==================== 主流程 ====================

def run(args):
    channels = load_channels()
    if not TOKEN and not args.dry_run:
        print("❌ 缺少 TG_TOKEN")
        return 1
    if not channels:
        print("❌ 频道配置为空（channels.json / CHANNELS_MEIRENTU）")
        return 1
    if not TELEGRAPH_TOKEN and not args.dry_run:
        print("❌ 未配置 TELEGRAPH_TOKEN，无法创建 Telegraph 页面，退出")
        return 1

    print("✅ 频道配置:")
    for ch in channels:
        desc = "全部图片" if ch["max_images"] == 0 else f"前 {ch['max_images']} 张"
        print(f"   - {ch['chat_id']}（{desc}{'，带会员引导' if ch['vip_link'] else ''}）")
    print("🚀 meirentu.cc 图集抓取 → pixhost → Telegraph → 多频道")

    seen_path = os.path.join(args.state_dir, "meirentu_seen.json")
    seen_file = state_core.StateFile(seen_path)
    seen = seen_file.load()

    page_path = os.path.join(args.state_dir, "meirentu_page.txt")
    page = state_core.load_page(page_path, args.start_page or START_PAGE)
    print(f"📌 当前页码: {page}，每日上限: {ALBUMS_PER_DAY} 套")

    dry_run = args.dry_run
    limit = args.limit or ALBUMS_PER_DAY
    processed = 0
    while processed < limit:
        albums = get_albums_from_list(page)
        if not albums:
            print("❌ 列表页无内容，退出")
            return 1

        new_albums = [a for a in albums if a["album_id"] not in seen]
        print(f"  新图集: {len(new_albums)}/{len(albums)}")

        if not new_albums:
            if page <= MIN_PAGE:
                print("✅ 已爬完最新一页，任务完成")
                break
            page -= 1
            if not dry_run:
                state_core.save_page(page_path, page)
            print(f"本页已全部处理，翻到上一页（更新）→ 第 {page} 页")
            continue

        # 从页面最底往上处理（列表顶部是最新内容）
        new_albums = list(reversed(new_albums))
        quota_left = limit - processed
        taken = new_albums[:quota_left]
        for album in taken:
            process_album(album, seen, seen_file, channels, dry_run)
            processed += 1

        remaining_on_page = len(new_albums) - len(taken)
        if remaining_on_page > 0:
            print(f"本页还剩 {remaining_on_page} 套，明天继续")
            break

    print(f"\n🎉 本次完成 {processed} 套，下次从第 {page} 页继续")
    return 0


register("meirentu", "meirentu.cc 图集（原 xrw）", run)
