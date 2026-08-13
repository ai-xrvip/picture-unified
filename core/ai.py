"""统一 AI 调用（OpenAI 兼容 /chat/completions），429 自动退避。"""
import time

import requests


def ask_chat(base_url, api_key, model, system, user,
             max_tokens=800, temperature=0.4,
             attempts=3, retry_429_wait=60):
    """同步调用 OpenAI 兼容接口，成功返回 content 字符串，失败返回 None。"""
    if not api_key or not model:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = base_url.rstrip("/") + "/chat/completions"
    for attempt in range(attempts):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=30,
            )
            if r.status_code == 429:
                print(f"  ⚠️ AI 限流 (429)，等待 {retry_429_wait}s 重试 ({attempt+1}/{attempts})")
                time.sleep(retry_429_wait)
                continue
            if r.status_code != 200:
                print(f"  ⚠️ AI 接口异常 ({r.status_code}): {r.text[:120]}")
                return None
            content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
            return content or None
        except Exception as e:
            print(f"  ⚠️ AI 调用异常 (第{attempt+1}次): {e}")
            time.sleep(5 * (attempt + 1))
    return None
