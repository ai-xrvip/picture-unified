import json
import os
import re
import sys
import time

from urllib.parse import urljoin
import os
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core import ai as ai_core
from core import config as cfg
from core import images as img_core
from core import network
from core import state as state_core
from core import telegraph as tg_core
from core import telegram as tg_send
from .base import register

# ── 环境变量 ──────────────────────────────────────────────
TOKEN = cfg.getenv("TG_TOKEN_4KHD") or cfg.getenv("TG_TOKEN")
# AI 打标签：优先 AI_API_KEY（DeepSeek）；未配置时复用 eh 的 AGNES_API_KEY（Agnes，OpenAI 兼容）
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
TELEGRAPH_TOKEN = cfg.getenv("TELEGRAPH_TOKEN")

# ── 常量 ──────────────────────────────────────────────────
MAX_PAGES = 10
MIN_CAT_PAGES = 5
MAX_IMAGES = 9999
BASE_URL = "https://www.4khd.com/"
CROP_RATIO = 0.015   # 四边各裁 1.5%
TG_CAPTION_MAX = 1024

ALL_CATEGORIES = [
    "https://www.4khd.com/",
    "https://www.4khd.com/pages/cosplay",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = network.new_session(HEADERS)

# ============================================================
#  AI 标签（DeepSeek，OpenAI 兼容）
# ============================================================

def generate_tags_with_ai(title):
    if not AI_API_KEY:
        return None
    prompt = (
        "你是一个写真/Cosplay标签专家。根据以下写真标题，提取3-5个最贴切的标签。\n"
        "标签用中文或英文都可以，每个标签以#开头。\n"
        "重点关注：角色名、作品/游戏名、服装类型、风格特征。\n"
        "只返回标签，用空格分隔，不要任何解释。\n\n"
        f"标题: {title}\n\n"
        "示例输出: #Cosplay #兔女郎 #碧蓝航线 #泳装 #黑丝"
    )
    content = ai_core.ask_chat(
        AI_BASE_URL, AI_API_KEY, AI_MODEL, "",
        prompt, max_tokens=80, temperature=0.3, attempts=1,
    )
    if not content:
        return None
    tags = re.findall(r"#[\w一-鿿\-_]+", content)
    if not tags:
        tags = re.findall(r"[\w一-鿿]{2,8}", content)
        tags = [f"#{t}" for t in tags]
    return list(dict.fromkeys(tags))[:5]


# ============================================================
#  本地标签库（内建默认 + 外部 tags.json 可选覆盖）
# ============================================================

BUILTIN_TAG_LIBRARY = {
    "cosplay":     "Cosplay",
    "coser":       "COSER",
    "兔女郎":      "兔女郎",
    "bunny":       "兔女郎",
    "泳装":        "泳装",
    "swimsuit":    "泳装",
    "水着":        "泳装",
    "黑丝":        "黑丝",
    "白丝":        "白丝",
    "制服":        "制服",
    "jk":          "JK制服",
    "和服":        "和服",
    "kimono":      "和服",
    "旗袍":        "旗袍",
    "女仆":        "女仆装",
    "maid":        "女仆装",
    "碧蓝航线":    "碧蓝航线",
    "azur":        "碧蓝航线",
    "原神":        "原神",
    "genshin":     "原神",
    "崩坏":        "崩坏",
    "honkai":      "崩坏",
    "fate":        "Fate",
    "尼尔":        "尼尔",
    "nier":        "尼尔",
    "蕾姆":        "Re:从零",
    "rem":         "Re:从零",
    "初音":        "初音未来",
    "miku":        "初音未来",
    "赛马娘":      "赛马娘",
    "明日方舟":    "明日方舟",
    "arknights":   "明日方舟",
    "少女前线":    "少女前线",
    "王者荣耀":    "王者荣耀",
    "lol":         "英雄联盟",
    "league":      "英雄联盟",
    "鬼灭":        "鬼灭之刃",
    "间谍":        "间谍过家家",
    "电锯人":      "电锯人",
    "eva":         "EVA",
    "福音":        "EVA",
    "最终幻想":    "最终幻想",
    "final":       "最终幻想",
    "ff7":         "最终幻想",
    "ff14":        "最终幻想",
    "ff15":        "最终幻想",
    "2b":          "尼尔",
    "asuka":       "EVA",
    "rei":         "EVA",
    "saber":       "Fate",
    "mash":        "Fate",
    "scathach":    "Fate",
    "tifa":        "最终幻想",
    "aerith":      "最终幻想",
    "yor":         "间谍过家家",
    "makima":      "电锯人",
    "power":       "电锯人",
    "raiden":      "雷电将军",
    "shogun":      "雷电将军",
    "ganyu":       "甘雨",
    "hutao":       "胡桃",
    "keqing":      "刻晴",
    "ayaka":       "神里绫华",
    "yoimiya":     "宵宫",
    "nilou":       "妮露",
    "nahida":      "纳西妲",
    "furina":      "芙宁娜",
    "arlecchino":  "阿蕾奇诺",
    "clorinde":    "克洛琳德",
    "firefly":     "流萤",
    "acheron":     "黄泉",
    "kafka":       "卡芙卡",
}


def load_tag_library():
    """优先加载外部 tags.json（仓库根目录），不存在则使用内建标签库"""
    try:
        with open("tags.json", "r", encoding="utf-8") as f:
            lib = json.load(f)
            print(f"✅ 外部标签库已加载，共 {len(lib)} 个标签")
            return {**BUILTIN_TAG_LIBRARY, **lib}
    except FileNotFoundError:
        return dict(BUILTIN_TAG_LIBRARY)
    except Exception as e:
        print(f"⚠️ 无法解析 tags.json: {e}，回退到内建标签库")
        return dict(BUILTIN_TAG_LIBRARY)


TAG_LIBRARY = load_tag_library()


def generate_tags_local(title, image_urls):
    tags = set()
    title_lower = title.lower()
    for key, tag in TAG_LIBRARY.items():
        if tag and key.lower() in title_lower:
            tags.add(f"#{tag}")
    for url in image_urls[:10]:
        url_lower = url.lower()
        for key, tag in TAG_LIBRARY.items():
            if tag and key.lower() in url_lower:
                tags.add(f"#{tag}")
    name_matches = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)+", title)
    for name in name_matches[:2]:
        tag_name = name.replace(" ", "")
        mapped_tag = TAG_LIBRARY.get(tag_name.lower())
        if mapped_tag:
            tags.add(f"#{mapped_tag}")
    if not tags:
        tags = {"#美女", "#写真"}
    return list(tags)[:6]


def generate_tags(title, image_urls):
    """优先 AI，回退本地标签库"""
    ai_tags = generate_tags_with_ai(title)
    if ai_tags:
        return ai_tags
    return generate_tags_local(title, image_urls)


# ============================================================
#  工具函数
# ============================================================

def clean_title(title):
    title = re.sub(r"\[[^\]]*\]", "", title)
    return re.sub(r"\s+", " ", title).strip()


def fix_image_url(src):
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif not src.startswith("http"):
        src = BASE_URL.rstrip("/") + "/" + src.lstrip("/")
    src = re.sub(r"https?://i\d+\.wp\.com/", "https://", src)
    src = src.replace("pic.4khd.com", "img.4khd.com")
    if "?" in src:
        src = src.split("?")[0]
    return src


def extract_images_from_content(soup):
    images, seen = [], set()
    content = None
    for sel in ["article", ".entry-content", ".post-body", ".single-content", "main"]:
        content = soup.select_one(sel)
        if content:
            break
    if not content:
        content = soup.find("body")
    if not content:
        return images

    AD_WORDS = {"related", "recommend", "popular", "ad", "banner", "widget", "sidebar", "footer"}

    def is_ad(tag):
        node = tag.parent
        for _ in range(3):
            if node and node.name in ["div", "aside", "section", "article", "li", "figure", "a"]:
                txt = " ".join(node.get("class", [])) + " " + (node.get("id") or "")
                if any(w in txt.lower() for w in AD_WORDS):
                    return True
            node = node.parent if node else None
        return False

    for ns in content.find_all("noscript"):
        inner = BeautifulSoup(ns.text, "html.parser")
        for img in inner.find_all("img"):
            src = fix_image_url(img.get("src"))
            if src and "4khd.com" in src and src not in seen:
                images.append(src)
                seen.add(src)

    for img in content.find_all("img"):
        if is_ad(img):
            continue
        src = fix_image_url(
            img.get("src") or img.get("data-src") or img.get("data-original") or ""
        )
        if src and "4khd.com" in src and src not in seen:
            images.append(src)
            seen.add(src)
    return images


def get_all_page_urls(first_url, soup):
    urls = [first_url]
    for a in soup.select("div.page-link-box ul.page-links li.numpages a.page-numbers"):
        href = a.get("href")
        if href:
            full = urljoin(first_url, href)
            if full not in urls:
                urls.append(full)
    return urls


def get_real_images(post_url):
    print(f"  🔍 {post_url}")
    r = network.safe_get(SESSION, post_url)
    if not r:
        return []
    soup_first = BeautifulSoup(r.text, "html.parser")
    page_urls = get_all_page_urls(post_url, soup_first)[:MAX_PAGES]
    print(f"  📖 {len(page_urls)} 个分页（最多{MAX_PAGES}页）")
    all_images, seen = [], set()
    for idx, url in enumerate(page_urls, 1):
        r2 = network.safe_get(SESSION, url)
        if not r2:
            continue
        soup = BeautifulSoup(r2.text, "html.parser")
        imgs = extract_images_from_content(soup)
        for u in re.findall(r"https://yt4\.googleusercontent\.com[^\s\"]+\.webp", r2.text):
            u = u.split("?")[0]
            if u not in seen:
                imgs.append(u)
        new_imgs = [u for u in imgs if u not in seen]
        all_images.extend(new_imgs)
        seen.update(new_imgs)
        print(f"  📄 第{idx}页 {len(new_imgs)} 张，累计 {len(all_images)} 张")
        time.sleep(0.5)
    return all_images[:MAX_IMAGES]


# ============================================================
#  列表抓取（多主题兼容）
# ============================================================

def get_new_posts_from_pages(pages, min_pages=MIN_CAT_PAGES):
    all_categorized_posts = []
    global_seen_urls = set()

    for page_url in pages:
        print(f"\n===== 抓取分类: {page_url} =====")
        r = network.safe_get(SESSION, page_url)
        if not r:
            all_categorized_posts.append([])
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        cat_pages = get_all_page_urls(page_url, soup)
        print(f"  从导航提取 {len(cat_pages)} 个分页")

        if len(cat_pages) < min_pages:
            existing_nums = set()
            for u in cat_pages:
                m = re.search(r"/page/(\d+)/?", u)
                if m:
                    existing_nums.add(int(m.group(1)))
                else:
                    m = re.search(r"[?&]page=(\d+)", u)
                    if m:
                        existing_nums.add(int(m.group(1)))
            start = max(existing_nums) + 1 if existing_nums else 2
            base = page_url.rstrip("/")
            for p in range(start, min_pages + 1):
                new_url = f"{base}/page/{p}/"
                if new_url not in cat_pages:
                    cat_pages.append(new_url)
            print(f"  补充后共 {len(cat_pages)} 个分页")

        cat_pages_sorted = cat_pages[:min_pages][::-1]
        print("  页面抓取顺序（从旧到新）:")
        for c in cat_pages_sorted:
            print(f"    {c}")

        category_posts = []
        for idx, cat_url in enumerate(cat_pages_sorted, 1):
            print(f"  📄 第{idx}页: {cat_url}")
            r2 = network.safe_get(SESSION, cat_url)
            page_posts = []
            if r2:
                soup = BeautifulSoup(r2.text, "html.parser")

                # 多主题兼容：尝试多种常见 WordPress 主题的选择器
                articles = None
                for selector in [
                    "li.wp-block-post",
                    "article",
                    ".post",
                    ".post-item",
                    ".entry",
                    ".blog-post",
                ]:
                    articles = soup.select(selector)
                    if articles:
                        break
                if not articles:
                    articles = soup.find_all("article") or []

                for art in reversed(articles):
                    title_el = (
                        art.find("h2", class_="wp-block-post-title")
                        or art.find("h2")
                        or art.find("h3")
                        or art.find("h1")
                    )
                    if not title_el:
                        continue
                    link = title_el.find("a", href=True)
                    if not link:
                        continue
                    href = link["href"]
                    title = link.text.strip()
                    if not title:
                        continue
                    full = href if href.startswith("http") else BASE_URL.rstrip("/") + href
                    if full in global_seen_urls:
                        print(f"    ⏭️ 已抓取过: {title[:50]}...")
                        continue

                    cover_src = ""
                    figure = (
                        art.find("figure", class_="wp-block-post-featured-image")
                        or art.find("figure")
                    )
                    if figure:
                        cover_img = figure.find("img")
                        if cover_img:
                            cover_src = fix_image_url(
                                cover_img.get("src")
                                or cover_img.get("data-src")
                                or ""
                            )

                    page_posts.append({"title": title, "url": full, "cover_url": cover_src})
                    global_seen_urls.add(full)
                    print(f"    ✅ 新帖: {title[:50]}... | {full}" +
                          (f" | 🖼️ {cover_src[:30]}..." if cover_src else ""))
                print(f"    本页新增 {len(page_posts)} 条")
            category_posts.append(page_posts)
            time.sleep(0.3)

        all_categorized_posts.append(category_posts)

    final_posts = []
    max_pages = max((len(cp) for cp in all_categorized_posts), default=0)
    print(f"\n===== 按页交错排列（{max_pages}页 × {len(pages)}分类）=====")
    for page_idx in range(max_pages - 1, -1, -1):
        for cat_idx in range(len(pages)):
            if page_idx < len(all_categorized_posts[cat_idx]):
                posts = all_categorized_posts[cat_idx][page_idx]
                if posts:
                    cat_name = pages[cat_idx].split("/")[-2] if pages[cat_idx] != BASE_URL else "popular"
                    print(f"  🔄 分类[{cat_name}] 第{page_idx+1}页 → {len(posts)} 条")
                    final_posts.extend(posts)

    print(f"\n===== 共 {len(final_posts)} 条候选帖子（按页交错排列）=====")
    return final_posts


# ============================================================
#  封面 / 文案 / 发送
# ============================================================

def build_caption(clean_t, tag_str, telegraph_url):
    """构建 Telegram caption，确保不超 1024 字符"""
    base = f"<b>{clean_t}</b>"
    tag_part = f"\n{tag_str}" if tag_str else ""
    if telegraph_url:
        link_part = f"\n\n<a href=\"{telegraph_url}\">👉 点击查看完整图集</a>"
    else:
        link_part = "\n\n⚠️ Telegraph 页面生成失败"

    full = base + tag_part + link_part
    if len(full) <= TG_CAPTION_MAX:
        return full

    # 优先保留标题 + 链接，截断标签
    shortened = base + link_part
    if len(shortened) <= TG_CAPTION_MAX:
        available = TG_CAPTION_MAX - len(shortened) - 3
        if available > 0:
            truncated_tags = tag_part[:available].rsplit(" ", 1)[0]
            return base + truncated_tags + link_part
        return shortened

    # 最坏情况：截断标题
    available_for_title = TG_CAPTION_MAX - len(link_part) - len("<b></b>")
    if available_for_title < 10:
        return link_part.strip()
    truncated_title = clean_t[:available_for_title] + "…"
    return f"<b>{truncated_title}</b>{link_part}"


def process_post(title, post_url, cover_url_from_list, channels, dry_run):
    """处理单个帖子，成功返回 True。dry_run 时只统计不发送。"""
    clean_t = clean_title(title) or title.strip()
    print(f"\n📥 {clean_t[:60]}")

    urls = get_real_images(post_url)
    if not urls:
        print("  ❌ 无图片")
        return False
    print(f"  图片总数: {len(urls)}")

    tags = generate_tags(clean_t, urls)
    tag_str = " ".join(tags)
    print(f"  🏷️ 标签: {tag_str}")

    if dry_run:
        print(f"  [dry-run] 将发送到 {len(channels)} 个频道，Telegraph 直嵌 {len(urls)} 张原图")
        return True

    telegraph_url = tg_core.create_page(
        TELEGRAPH_TOKEN, clean_t, urls,
        author_name="4KHD Bot", footer="promo",
    )

    cover_item = None
    if cover_url_from_list:
        print(f"  📸 下载列表封面: {cover_url_from_list[:80]}")
        raw = img_core.download_image(
            SESSION, cover_url_from_list, referer=post_url,
            max_size_mb=50, retries=2, validate=False,
        )
        if raw[0]:
            data, ctype = raw
            cover_item = (img_core.crop_image(data), ctype)
    if not cover_item:
        print("  ❌ 封面获取失败")
        return False

    caption = build_caption(clean_t, tag_str, telegraph_url)
    ok = tg_send.send_photo(TOKEN, channels[0]["chat_id"], cover_item[0], cover_item[1], caption)
    if not ok:
        print("  ❌ 频道发送失败")
        return False
    print("  ✅ 已发送到频道")

    # 可选群组：失败仅警告，不算整体失败
    for ch in channels[1:]:
        cover_data, cover_ctype = cover_item
        cover_data.seek(0)

        group_ok = tg_send.send_photo(
            TOKEN, ch["chat_id"], BytesIO(cover_data.read()), cover_ctype, caption
        )
        if group_ok:
            print(f"  ✅ 已发送到群组 {ch['chat_id']}")
        else:
            print(f"  ⚠️ 群组 {ch['chat_id']} 发送失败")
    return True


# ============================================================
#  主入口
# ============================================================

def run(args):
    global TELEGRAPH_TOKEN
    if not TOKEN and not args.dry_run:
        print("❌ 缺少 TG_TOKEN")
        return 1

    channels = cfg.load_channels("4khd")
    if not channels:
        print("❌ 4khd 频道配置为空")
        return 1
    main_chat_id = channels[0]["chat_id"]
    if not main_chat_id and not args.dry_run:
        print("❌ 缺少主频道 TG_CHAT_ID_4KHD")
        return 1

    print(f"✅ 频道: 主 {main_chat_id}" +
          (f" + 群组 {[c['chat_id'] for c in channels[1:]]}" if len(channels) > 1 else ""))

    if args.dry_run:
        print("  [dry-run] 跳过 Telegraph token 初始化")
    else:
        TELEGRAPH_TOKEN = tg_core.get_or_create_token(
            TELEGRAPH_TOKEN, "4KHD", "4KHD Bot",
            cache_file=os.path.join(args.state_dir, "4khd_telegraph.token"),
        )

    seen_path = os.path.join(args.state_dir, "4khd_seen.json")
    seen_file = state_core.StateFile(seen_path)
    seen = seen_file.load()
    print(f"📂 seen 记录: {len(seen)} 条")

    posts = get_new_posts_from_pages(ALL_CATEGORIES, MIN_CAT_PAGES)
    new_posts = [p for p in posts if p["url"] not in seen]

    if not new_posts:
        print("暂无新内容")
        seen_file.save(seen)
        return 0

    print(f"发现 {len(new_posts)} 条新内容（发送顺序：从旧到新）")
    success = 0
    for i, p in enumerate(new_posts, 1):
        ok = process_post(p["title"], p["url"], p.get("cover_url", ""), channels, args.dry_run)
        if ok:
            seen.add(p["url"])
            success += 1
        else:
            print(f"  ⚠️ 发送失败，下次运行会重试: {p['url']}")
        print(f"  进度 {i}/{len(new_posts)}，成功 {success} 条")
        if i % 3 == 0 and not args.dry_run:
            seen_file.save(seen)
        if args.limit and success >= args.limit:
            print(f"⏹ 已达本次上限 {args.limit} 条")
            break
        time.sleep(10)

    if not args.dry_run:
        seen_file.save(seen)
    print(f"\n✅ 完成 {success}/{len(new_posts)} 条")
    return 0


register("4khd", "4khd.com 写真/Cosplay（原 4khd）", run)
