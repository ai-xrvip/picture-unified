"""统一 Telegraph 页面创建。"""
import os

import requests

PROMO_IMG = "https://i.ibb.co/bYwH4Y2/Chat-GPT-Image-2026-7-2-23-55-12.png"
PROMO_BOT = "http://t.me/fljtkwbot"


def create_page(token, title, image_urls, author_name="Picture Bot",
                footer=None, vip_link=None, title_max=256):
    """用图片直链创建 Telegraph 页面。
    footer: None=无页脚; "promo"=推广图+搜索bot; "vip"=会员引导链接
    """
    if not token:
        print("  ⚠️ 未配置 TELEGRAPH_TOKEN")
        return None
    if not image_urls:
        return None

    children = [{"tag": "img", "attrs": {"src": url}} for url in image_urls]
    if footer == "promo":
        children.append({"tag": "img", "attrs": {"src": PROMO_IMG}})
        children.append({
            "tag": "p",
            "children": [
                {"tag": "a", "attrs": {"href": PROMO_BOT},
                 "children": ["🔍 点击搜索更多图集、Cos、福利姬… 懂的都懂 👀"]}
            ],
        })
    elif footer == "vip" and vip_link:
        children.append({
            "tag": "h3",
            "children": [
                "🚀 查看完整版图集，点击 ",
                {"tag": "a", "attrs": {"href": vip_link}, "children": ["✨ 加入会员群 ✨"]},
            ],
        })

    try:
        r = requests.post(
            "https://api.telegra.ph/createPage",
            json={
                "access_token": token,
                "title": title[:title_max],
                "author_name": author_name,
                "content": children,
                "return_content": False,
            },
            timeout=30,
        )
        resp = r.json()
        if r.status_code == 200 and resp.get("ok"):
            url = resp["result"]["url"]
            print(f"  ✅ Telegraph 页面: {url}")
            return url
        print(f"  ❌ Telegraph 页面创建失败: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ Telegraph 异常: {e}")
    return None


def get_or_create_token(env_token, short_name, author_name, cache_file=None):
    """优先环境变量；其次缓存文件；最后新建账号（4khd 旧行为）。"""
    if env_token:
        return env_token
    if cache_file and os.path.exists(cache_file):
        token = open(cache_file).read().strip()
        if token:
            return token
    try:
        r = requests.post(
            "https://api.telegra.ph/createAccount",
            json={"short_name": short_name, "author_name": author_name},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("ok"):
            token = r.json()["result"]["access_token"]
            if cache_file:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "w") as f:
                    f.write(token)
            return token
        print(f"  ❌ Telegraph token 创建失败: {r.text}")
    except Exception as e:
        print(f"  ❌ Telegraph 初始化异常: {e}")
    return None
