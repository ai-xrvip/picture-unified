#!/usr/bin/env python3
"""统一爬取入口。

用法：
  python run.py eh                     # e-hentai cosplay
  python run.py meirentu               # meirentu.cc（原 xrw）
  python run.py 4khd                   # 4khd.com
  python run.py meirentu --dry-run     # 只抓取分析，不下载不发送不改状态
  python run.py eh --limit 3           # 本次最多处理 3 条
  python run.py --list                 # 列出数据源
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sources import eh, k4hd, meirentu  # noqa: E402,F401  触发注册
from sources.base import REGISTRY  # noqa: E402

ALIASES = {"4k": "4khd", "4khd.com": "4khd", "xrw": "meirentu"}


def main():
    parser = argparse.ArgumentParser(description="统一爬取入口")
    parser.add_argument("source", nargs="?", help="数据源: eh / meirentu / 4khd")
    parser.add_argument("--limit", type=int, default=0, help="本次处理上限（0=按源默认/不限制）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取分析，不下载不发送不改状态")
    parser.add_argument("--start-page", type=int, default=0, help="meirentu 起始页覆盖")
    parser.add_argument("--state-dir", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "state"), help="状态目录（默认 state/）")
    parser.add_argument("--list", action="store_true", help="列出数据源")
    args = parser.parse_args()

    if args.list or not args.source:
        print("可用数据源:")
        for name, src in REGISTRY.items():
            print(f"  {name:10s} {src['label']}")
        return 0

    name = ALIASES.get(args.source, args.source)
    if name not in REGISTRY:
        print(f"❌ 未知数据源: {args.source}（可用: {', '.join(REGISTRY)}）")
        return 2

    os.makedirs(args.state_dir, exist_ok=True)
    return REGISTRY[name]["run"](args)


if __name__ == "__main__":
    sys.exit(main())
