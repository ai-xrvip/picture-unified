"""统一图床层：pixhost 上传（eh/xrw 原逻辑合并）。"""
import time

import requests

from .images import detect_ext, is_valid_image

MAX_RETRIES = 3
RETRY_DELAY_BASE = 5
RETRY_DELAY_MAX = 15


def verify_image_url(url):
    """下载上传后的直链并用 PIL 验证是否为真实图片"""
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and len(r.content) > 5000:
            return is_valid_image(r.content)
    except Exception:
        pass
    return False


def upload_pixhost(image_data):
    """pixhost.to 上传（content_type=1 成人内容）+ 验证 + 递增退避重试。成功返回直链，失败返回 None。"""
    ext = detect_ext(image_data)
    for attempt in range(MAX_RETRIES + 1):  # 总共尝试 4 次
        url = None
        try:
            r = requests.post(
                "https://api.pixhost.to/images",
                data={"content_type": "1"},  # 1 = 成人内容
                files={"img": (f"image.{ext}", image_data, f"image/{ext}")},
                timeout=30,
            )
            if r.status_code == 200:
                resp = r.json()
                if resp.get("show_url"):
                    url = resp["show_url"].replace(
                        "https://pixhost.to/show/", "https://img2.pixhost.to/images/"
                    )
        except Exception as e:
            print(f"    ⚠️ pixhost 异常: {e}")

        if url and verify_image_url(url):
            return url

        if attempt < MAX_RETRIES:
            delay = min(RETRY_DELAY_BASE * (attempt + 1), RETRY_DELAY_MAX)
            print(f"    🔄 重试 {attempt+1}/{MAX_RETRIES}，等待 {delay}s...")
            time.sleep(delay)

    return None
