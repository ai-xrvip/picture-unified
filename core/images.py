"""统一图片工具：校验、下载、裁剪、封面选择。"""
import time
from io import BytesIO

from PIL import Image


def is_valid_image(data):
    """验证图片文件是否完整可解码"""
    try:
        img = Image.open(BytesIO(data))
        img.verify()
        return True
    except Exception:
        return False


def detect_ext(data):
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"RIFF":
        return "webp"
    return "jpg"


def download_image(session, url, referer=None, max_size_mb=10, retries=3, validate=True):
    """下载图片，返回 (BytesIO, content_type) 或 (None, None)。"""
    for attempt in range(retries):
        try:
            headers = {"Referer": referer} if referer else {}
            r = session.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "image/jpeg")
            if not ct.startswith("image/"):
                continue
            if len(r.content) < 2000:
                continue
            if len(r.content) > max_size_mb * 1024 * 1024:
                print(f"    ⚠️ 图片过大 ({len(r.content)//1024}KB)，跳过")
                return None, None
            if validate and not is_valid_image(r.content):
                print("    ⚠️ 图片损坏，重试")
                continue
            return BytesIO(r.content), ct
        except Exception as e:
            print(f"    ❌ 下载失败 ({attempt+1}/{retries}): {e}")
            time.sleep(1)
    return None, None


def pick_cover(images):
    """优先竖图（1.2~3.0 比例）中字节数最大的，否则全图中最大，最后兜底第一张。"""
    portrait, all_imgs = [], []
    for data in images:
        try:
            img = Image.open(BytesIO(data))
            w, h = img.size
            if w == 0 or h == 0:
                continue
            ratio = h / w
            size = len(data)
            all_imgs.append((size, data))
            if h > w and 1.2 <= ratio <= 3.0:
                portrait.append((size, data))
        except Exception as e:
            print(f"  ⚠️ 无法解析图片尺寸: {e}")
            continue
    if portrait:
        print(f"  📐 找到 {len(portrait)} 张合适竖图，选最大的作封面")
        return max(portrait, key=lambda x: x[0])[1]
    if all_imgs:
        print("  ⚠️ 没有合适竖图，从所有图中选最大的作封面")
        return max(all_imgs, key=lambda x: x[0])[1]
    print("  ⚠️ 无法解析任何图片，使用第一张作封面")
    return images[0]


def crop_image(img_bytes, crop_ratio=0.015, fmt="JPEG", quality=95):
    """裁剪四边各 crop_ratio（默认 1.5%），失败返回原图。"""
    try:
        with Image.open(img_bytes) as img:
            w, h = img.size
            l = int(w * crop_ratio)
            t = int(h * crop_ratio)
            r = int(w * (1 - crop_ratio))
            b = int(h * (1 - crop_ratio))
            cropped = img.crop((l, t, r, b)).convert("RGB")
            out = BytesIO()
            if fmt == "WEBP":
                cropped.save(out, format="WEBP", quality=quality, method=6)
            else:
                cropped.save(out, format="JPEG", quality=quality)
            out.seek(0)
            return out
    except Exception as e:
        print(f"  ⚠️ 裁剪失败: {e}")
        img_bytes.seek(0)
        return img_bytes
