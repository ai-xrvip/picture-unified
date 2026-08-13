"""统一 Telegram 发送（requests 直连 Bot API）。"""
import time

import requests


def send_photo(token, chat_id, photo_data, photo_ctype, caption, retries=3):
    """发送封面到频道，429 自动等待。成功返回 True。"""
    ext = photo_ctype.split("/")[-1].replace("jpeg", "jpg")
    for attempt in range(retries):
        photo_data.seek(0)
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": (f"cover.{ext}", photo_data, photo_ctype)},
                timeout=30,
            )
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                try:
                    wait = r.json().get("parameters", {}).get("retry_after", 30)
                except Exception:
                    wait = 30
                print(f"  ⚠️ Telegram 限流，等待 {wait}s")
                time.sleep(wait)
            else:
                print(f"  ❌ sendPhoto 失败 ({r.status_code}): {r.text[:200]}")
                time.sleep(2)
        except Exception as e:
            print(f"  ❌ sendPhoto 异常 (attempt {attempt+1}): {e}")
            time.sleep(2)
    return False
