"""统一配置工具：环境变量读取、${VAR} 引用解析、频道配置加载。"""
import json
import os
import sys


def getenv(name, default=""):
    return os.getenv(name, default).strip()


def resolve_ref(value, env=None):
    """把 "${VAR}" 解析为环境变量值。
    - 普通字符串原样返回
    - "${VAR}" 已设置且非空 → 返回值
    - "${VAR}" 未设置 → 返回 None，由调用方决定默认值/跳过
    """
    env = os.environ if env is None else env
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        name = value[2:-1]
        if name in env and env[name].strip():
            return env[name].strip()
        return None
    return value


def load_channels(source, channels_json="channels.json"):
    """频道配置：优先环境变量 CHANNELS_<SOURCE>（JSON），否则读 channels.json 对应段。
    每项支持: chat_id / max_images / vip_link / optional / group
    """
    raw = getenv(f"CHANNELS_{source.upper()}")
    if raw:
        data = json.loads(raw)
    else:
        with open(channels_json, "r", encoding="utf-8-sig") as f:
            data = json.load(f).get(source, [])
    channels = []
    for ch in data:
        chat_id = resolve_ref(ch.get("chat_id", ""))
        if not chat_id:
            if ch.get("optional"):
                continue
            print(f"  ⚠️ 频道配置缺少 chat_id（{source}），且非 optional，跳过该频道")
            continue
        channels.append({
            "chat_id": str(chat_id),
            "max_images": int(ch.get("max_images", 0) or 0),
            "vip_link": resolve_ref(ch["vip_link"]) if "vip_link" in ch else None,
            "optional": bool(ch.get("optional", False)),
        })
    return channels


def require(*names):
    missing = [n for n in names if not getenv(n)]
    if missing:
        print(f"❌ 缺少环境变量: {', '.join(missing)}")
        sys.exit(1)
