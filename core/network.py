"""统一网络工具：带重试的 GET、会话构建。"""
import time

import requests


def new_session(headers=None, cookies=None):
    s = requests.Session()
    if headers:
        s.headers.update(headers)
    if cookies:
        s.cookies.update(cookies)
    return s


def safe_get(session, url, retries=3, timeout=20, **kw):
    """GET 重试：200 返回；429 按 Retry-After 等待；其余退避重试。失败返回 None。"""
    for i in range(retries):
        try:
            r = session.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                try:
                    wait = int(r.headers.get("Retry-After", 30))
                except (TypeError, ValueError):
                    wait = 30
                print(f"  ⏳ 限流 429，等待 {wait}s")
                time.sleep(wait)
            else:
                print(f"  ⚠️ HTTP {r.status_code}: {url}（第 {i+1}/{retries} 次）")
                time.sleep(2)
        except Exception as e:
            print(f"  ❌ 请求异常 ({i+1}/{retries}): {e}")
            time.sleep(2)
    return None
