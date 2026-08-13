"""一次性迁移旧项目状态到统一仓库 state/。

用法：
  python migrate_state.py                        # 默认读取 E:/codex/picture
  python migrate_state.py --legacy E:/codex/picture --state state
"""
import argparse
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_set(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
        if isinstance(data, dict):
            return set(data.keys())
    except Exception as e:
        print(f"  ⚠️ 读取失败 {path}: {e}")
    return set()


def write_set(path, values):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(values), f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="迁移旧项目状态")
    parser.add_argument("--legacy", default=r"E:\codex\picture", help="旧项目根目录")
    parser.add_argument("--state", default="state", help="统一状态目录")
    args = parser.parse_args()

    # eh: sent_galleries.json -> eh_seen.json
    eh_seen = load_set(os.path.join(args.legacy, "eh", "sent_galleries.json"))
    write_set(os.path.join(args.state, "eh_seen.json"), eh_seen)
    print(f"✅ eh     : {len(eh_seen)} 条 -> state/eh_seen.json")

    # xrw -> meirentu: seen.json -> meirentu_seen.json, next_page.txt -> meirentu_page.txt
    me_seen = load_set(os.path.join(args.legacy, "xrw", "seen.json"))
    write_set(os.path.join(args.state, "meirentu_seen.json"), me_seen)
    page_src = os.path.join(args.legacy, "xrw", "next_page.txt")
    if os.path.exists(page_src):
        with open(page_src, "r", encoding="utf-8") as f:
            page = f.read().strip()
        with open(os.path.join(args.state, "meirentu_page.txt"), "w", encoding="utf-8") as f:
            f.write(page)
        print(f"✅ meirentu: {len(me_seen)} 条 + 页码 {page} -> state/")
    else:
        print(f"✅ meirentu: {len(me_seen)} 条 -> state/meirentu_seen.json（未找到 next_page.txt）")

    # 4khd: seen_posts.json -> 4khd_seen.json
    k4_seen = load_set(os.path.join(args.legacy, "4khd", "seen_posts.json"))
    write_set(os.path.join(args.state, "4khd_seen.json"), k4_seen)
    print(f"✅ 4khd   : {len(k4_seen)} 条 -> state/4khd_seen.json")

    print("\n🎉 迁移完成，统一仓库启动后不会重复发布。")


if __name__ == "__main__":
    main()
