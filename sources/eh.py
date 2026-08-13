"""e-hentai.org cosplay 图集源（原 eh 项目 main.py 的同步移植）。

流程：抓列表(f_cats=959) → 抓图集图片直链 → 逐张下载 → pixhost 上传 →
Telegraph 页面(页尾推广) → AI 中文标题+标签 → 封面发频道。
状态：state/eh_seen.json（uid = gid_token）
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from bs4 import BeautifulSoup

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
BOT_TOKEN = cfg.getenv("BOT_TOKEN")
MAIN_CHANNEL = cfg.getenv("MAIN_CHANNEL_ID")
EH_MEMBER_ID = cfg.getenv("EH_MEMBER_ID")
EH_PASS_HASH = cfg.getenv("EH_PASS_HASH")
EH_CF_CLEARANCE = cfg.getenv("EH_CF_CLEARANCE")
TELEGRAPH_TOKEN = cfg.getenv("TELEGRAPH_TOKEN")
# AI 打标签：优先 DeepSeek（AI_API_KEY）；未配置时回退 Agnes（AGNES_API_KEY）
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

# ── 常量 ──────────────────────────────────────────────────
COSPLAY_URL = "https://e-hentai.org/?f_cats=959"
MAX_PAGES = 20
LIST_PAGES = 1
UPLOAD_DELAY = 1  # 每张图片上传间隔（秒）

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Referer": "https://e-hentai.org/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def build_cookies():
    cookies = {
        "ipb_member_id": EH_MEMBER_ID,
        "ipb_pass_hash": EH_PASS_HASH,
    }
    if EH_CF_CLEARANCE:
        cookies["cf_clearance"] = EH_CF_CLEARANCE
    return cookies


# ========= 标题清洗 / 规则标签兜底 =========

def clean_title(title):
    title = re.sub(r"\[.*?\]", "", title)
    title = re.sub(r"f:[^ ]+", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def generate_tags(title: str) -> str:
    stop_words = {
        "by", "the", "of", "and", "or", "for", "with", "from", "to", "in", "on", "at",
        "is", "are", "a", "an", "photo", "photos", "set", "collection", "comic",
        "comiket", "c", "vol", "volume", "part", "chapter", "artist", "pixiv",
        "twitter", "fanbox", "patreon", "x", "new", "view", "full", "gallery",
    }
    words = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", title)
    tags = []
    for w in words:
        if w.lower() in stop_words:
            continue
        if len(w) <= 1 and not w.isdigit():
            continue
        if f"#{w}" not in tags:
            tags.append(f"#{w}")
    return " ".join(tags)


# ========= AI 标签（DeepSeek，OpenAI 兼容；沿用 4khd 提示词） =========

TAGS_SYSTEM_PROMPT = (
    "你是一个写真/Cosplay标签专家。根据以下写真标题，提取3-5个最贴切的标签。\n"
    "标签用中文或英文都可以，每个标签以#开头。\n"
    "重点关注：角色名、作品/游戏名、服装类型、风格特征。\n"
    "只返回标签，用空格分隔，不要任何解释。\n\n"
    "标题: {title}\n\n"
    "示例输出: #Cosplay #兔女郎 #碧蓝航线 #泳装 #黑丝"
)


def generate_tags_ai(title):
    """调用 DeepSeek 生成标签（4khd 同款提示词）；失败返回 None，由规则标签兜底。"""
    if not AI_API_KEY:
        print("  ⚠️ 未配置 AI_API_KEY，使用规则标签")
        return None
    content = ai_core.ask_chat(
        AI_BASE_URL, AI_API_KEY, AI_MODEL, "",
        TAGS_SYSTEM_PROMPT.format(title=title),
        max_tokens=80, temperature=0.3,
        attempts=2, retry_429_wait=30,
    )
    if not content:
        print("  ⚠️ AI 标签生成失败，使用规则标签")
        return None
    tags = re.findall(r"#[\w一-鿿\-_]+", content)
    if not tags:
        tags = re.findall(r"[\w一-鿿]{2,8}", content)
        tags = [f"#{t}" for t in tags]
    result = " ".join(list(dict.fromkeys(tags))[:8])
    print(f"  🤖 AI 标签: {result}")
    return result


# ========= 抓列表 =========

def get_galleries(session):
    galleries = []
    seen_urls = set()

    for page in range(LIST_PAGES):
        url = COSPLAY_URL if page == 0 else f"{COSPLAY_URL}&page={page}"
        print(f"  📄 列表第{page+1}页: {url}")
        r = network.safe_get(session, url, retries=2)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.select("a[href*='/g/']"):
            href = a.get("href", "")
            m = re.search(r"/g/(\d+)/([a-f0-9]+)/", href)
            if not m or href in seen_urls:
                continue
            seen_urls.add(href)

            title_node = a.select_one(".glink") or a.find(class_="glink")
            if not title_node:
                parent = a.parent
                for _ in range(5):
                    if not parent:
                        break
                    title_node = parent.select_one(".glink")
                    if title_node:
                        break
                    parent = parent.parent
            if not title_node:
                continue

            title = clean_title(title_node.text)
            if not title:
                continue

            galleries.append({
                "gid": m.group(1),
                "token": m.group(2),
                "url": href,
                "title": title,
            })

        time.sleep(1)

    galleries.reverse()
    print(f"  📋 共找到 {len(galleries)} 个图集（从最旧开始处理）")
    return galleries


# ========= 抓图集所有图片直链 =========

def get_all_image_urls(session, base_url):
    r = network.safe_get(session, base_url, retries=3)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")

    max_page = 0
    for a in soup.select(".ptt a"):
        try:
            max_page = max(max_page, int(a.text))
        except Exception:
            pass

    actual_pages = min(max_page + 1, MAX_PAGES)
    print(f"📄 页数: {max_page+1}，实际抓取: {actual_pages} 页")

    all_pages = []
    for i in range(actual_pages):
        url = f"{base_url}?p={i}"
        r2 = network.safe_get(session, url, retries=2)
        if not r2:
            continue
        soup = BeautifulSoup(r2.text, "html.parser")
        thumbs = [a["href"] for a in soup.select("#gdt a")]
        all_pages.extend(thumbs)
        print(f"  第{i}页: {len(thumbs)}")
        time.sleep(1)

    print(f"👉 图片页总数: {len(all_pages)}")

    def fetch_img_url(u):
        for attempt in range(3):
            try:
                r3 = session.get(u, timeout=20)
                soup = BeautifulSoup(r3.text, "html.parser")
                img = soup.select_one("#img")
                if img:
                    return img["src"]
            except Exception as e:
                print(f"  ⚠️ 图片页抓取失败 (第{attempt+1}次): {e}")
                time.sleep(3)
        return None

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(fetch_img_url, all_pages))
    return [x for x in results if x]


# ========= 下载单张图片 =========

def download_one(session, url):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200 and 5000 < len(r.content) < 10 * 1024 * 1024:
                if img_core.is_valid_image(r.content):
                    return r.content
                print("  ⚠️ 图片损坏，重试")
                continue
            if r.status_code == 509:
                print("  ⚠️ E-Hentai 509 流量超限，等待 60s...")
                time.sleep(60)
                continue
        except Exception as e:
            print(f"  ⚠️ 下载失败 (第{attempt+1}次): {e}")
            time.sleep(3)
    return None


# ========= 下载 → 上传 → 释放内存 =========

def download_and_upload_all(session, urls):
    """逐张下载 → pixhost 上传 → 释放内存。返回 (直链列表, 封面候选列表)"""
    img_urls = []
    cover_candidates = []
    total = len(urls)

    for i, url in enumerate(urls):
        data = download_one(session, url)
        if not data:
            print(f"  ⚠️ [{i+1}/{total}] 下载失败，跳过")
            continue

        if len(cover_candidates) < 20:
            cover_candidates.append(data)

        img_url = up_core.upload_pixhost(data)
        if img_url:
            img_urls.append(img_url)
            print(f"  ✅ [{i+1}/{total}] pixhost 上传成功")
        else:
            print(f"  ⚠️ [{i+1}/{total}] pixhost 上传失败，跳过")

        del data
        time.sleep(UPLOAD_DELAY)

    return img_urls, cover_candidates


# ========= 主流程 =========

def run(args):
    if not TELEGRAPH_TOKEN:
        print("❌ 未配置 TELEGRAPH_TOKEN，退出")
        return 1
    if not BOT_TOKEN or not MAIN_CHANNEL:
        print("❌ 缺少 BOT_TOKEN 或 MAIN_CHANNEL_ID")
        return 1

    channels = cfg.load_channels("eh")
    if not channels:
        print("❌ eh 频道配置为空")
        return 1
    chat_id = channels[0]["chat_id"]

    seen_path = os.path.join(args.state_dir, "eh_seen.json")
    seen_file = state_core.StateFile(seen_path)
    seen = seen_file.load()
    print(f"📂 已发记录: {len(seen)} 条")

    session = network.new_session(HEADERS, build_cookies())
    galleries = get_galleries(session)

    processed = 0
    for g in galleries:
        uid = f"{g['gid']}_{g['token']}"
        if uid in seen:
            print(f"⏭️ 跳过已发: {g['title']}")
            continue

        print(f"\n处理: {g['title']}")

        if args.dry_run:
            urls = get_all_image_urls(session, g["url"])
            print(f"  [dry-run] 图片直链 {len(urls)} 张，将上传 pixhost 并发送到 {chat_id}")
            processed += 1
            if args.limit and processed >= args.limit:
                print(f"⏹ 已达本次上限 {args.limit} 条")
                break
            continue

        urls = get_all_image_urls(session, g["url"])
        if not urls:
            print("  ⚠️ 未抓到图片 URL，跳过")
            seen.add(uid)
            seen_file.save(seen)
            continue

        print(f"  🔗 共获取 {len(urls)} 个图片 URL")
        img_urls, cover_candidates = download_and_upload_all(session, urls)

        if not img_urls:
            print("  ⚠️ 没有图片上传成功，跳过")
            seen.add(uid)
            seen_file.save(seen)
            continue

        print(f"  ✅ 成功上传 {len(img_urls)}/{len(urls)} 张到 pixhost")

        zh_title = g["title"]
        tags = generate_tags_ai(zh_title) or generate_tags(zh_title)

        telegraph_url = tg_core.create_page(
            TELEGRAPH_TOKEN, zh_title, img_urls,
            author_name="EH Cosplay Bot", footer="promo",
        )
        if not telegraph_url:
            print("  ⚠️ Telegraph 页面创建失败，跳过")
            seen.add(uid)
            seen_file.save(seen)
            continue

        if not cover_candidates:
            print("  ⚠️ 无封面候选，跳过")
            seen.add(uid)
            seen_file.save(seen)
            continue

        cover = img_core.pick_cover(cover_candidates)
        caption = (
            f"<b>{zh_title}</b>\n"
            f"{tags}\n\n"
            f"<a href='{telegraph_url}'>👉 点击查看图集/View Photo Gallery</a>"
        )
        ok = tg_send.send_photo(BOT_TOKEN, chat_id, BytesIO(cover), "image/jpeg", caption)
        if not ok:
            print("  ❌ 频道发送失败，不标记已发（下次重试）")
            continue

        print(f"  ✅ 发送完成: {g['title']}")
        seen.add(uid)
        seen_file.save(seen)
        processed += 1

        if args.limit and processed >= args.limit:
            print(f"⏹ 已达本次上限 {args.limit} 条")
            break

    print(f"\n🎉 eh 本次完成 {processed} 条")
    return 0


register("eh", "e-hentai.org cosplay 图集（原 eh）", run)
