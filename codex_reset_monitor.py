# -*- coding: utf-8 -*-
"""
cron: 23 * * * *
new Env('Codex重置监控');
name: Codex重置监控

数据源: https://codex-resets.com/api/v1/status
监控 OpenAI Codex 额度重置公告（跟踪 @thsottiaux 推文）。
"""
import os
import json
import hmac
import hashlib
import base64
import urllib.parse
import time
from datetime import datetime, timezone, timedelta

import requests

# 代理：CODEX_RESET_PROXY > AUTO_TASK_PROXY > 系统
def _proxy():
    for name in ("CODEX_RESET_PROXY", "AUTO_TASK_PROXY"):
        v = os.environ.get(name) or os.environ.get(name.lower())
        if v:
            return v.strip()
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        v = os.environ.get(key)
        if v:
            return v.strip()
    return ""


_http_proxy = _proxy()

# 推送
bark_push = os.environ.get("BARK_PUSH", "")
bark_push = f"https://api.day.app/{bark_push}" if bark_push and not bark_push.startswith("http") else bark_push
bark_group = "Codex"
bark_icon = "https://codex-resets.com/favicon.ico"
bark_sound = os.environ.get("BARK_SOUND", "")
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

API_STATUS = "https://codex-resets.com/api/v1/status"
API_RESETS = "https://codex-resets.com/api/v1/resets"
TITLE = "【autoTask】Codex重置监控"
STATE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(STATE_DIR, "codex_reset_state.json")
CST = timezone(timedelta(hours=8))


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_json(url, params=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "autoTask-codex-reset-monitor/1.0",
    }
    try:
        resp = requests.get(
            url,
            headers=headers,
            params=params or {},
            timeout=30,
            proxies={"http": _http_proxy, "https": _http_proxy} if _http_proxy else None,
        )
    except requests.RequestException as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if resp.status_code == 304:
        return {"not_modified": True}
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        return resp.json()
    except ValueError:
        return {"error": f"非 JSON: {resp.text[:200]}"}


def fmt_time(value):
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(CST)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return str(value)[:16].replace("T", " ")


def snippet(text, n=80):
    t = " ".join((text or "").split())
    return t[:n] + ("…" if len(t) > n else "")


def build_message(status_data, kind, item):
    """kind: latest | scheduled"""
    stats = status_data.get("stats") or {}
    L = []
    if kind == "latest":
        L.append("🎉 新的 Codex 额度重置已记录")
    else:
        L.append("📅 安排中的 Codex 重置")
    L.append(f"类型｜{item.get('reset_type') or '-'}")
    L.append(f"时间｜{fmt_time(item.get('announced_at') or item.get('scheduled_for'))}")
    if kind == "scheduled" and item.get("scheduled_for"):
        L.append(f"预定｜{fmt_time(item.get('scheduled_for'))}")
        L.append(f"状态｜{item.get('status') or 'scheduled'}")
    L.append(f"摘要｜{snippet(item.get('text'))}")
    src = item.get("source") or {}
    if src.get("url"):
        L.append(f"公告｜{src['url']}")
    L.append("")
    L.append(f"累计重置｜{stats.get('total', '-')}")
    if stats.get("days_since_last") is not None:
        L.append(f"距上次｜{float(stats['days_since_last']):.1f} 天")
    if stats.get("avg_interval_days") is not None:
        L.append(f"平均间隔｜{float(stats['avg_interval_days']):.1f} 天")
    return "\n".join(L)


def send_bark(text):
    if not bark_push:
        print("未配置 Bark，跳过")
        return
    payload = {
        "title": TITLE,
        "body": text,
        "icon": bark_icon,
        "sound": bark_sound,
        "group": bark_group,
    }
    try:
        r = requests.post(bark_push, json=payload, timeout=10)
        r.raise_for_status()
        print("✅ Bark 推送成功")
    except Exception as e:
        print(f"❌ Bark 推送失败: {e}")


def send_dingtalk(text):
    if not dingtalk_token:
        print("未配置钉钉，跳过")
        return
    content = f"{TITLE}\n\n{text}"
    data = {"msgtype": "text", "text": {"content": content}}
    if dingtalk_secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{dingtalk_secret}"
        sign = urllib.parse.quote_plus(
            base64.b64encode(
                hmac.new(
                    dingtalk_secret.encode("utf-8"),
                    string_to_sign.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            )
        )
        url = (
            f"https://oapi.dingtalk.com/robot/send"
            f"?access_token={dingtalk_token}&timestamp={timestamp}&sign={sign}"
        )
    else:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}"
    try:
        r = requests.post(url, json=data, timeout=10)
        r.raise_for_status()
        print("✅ 钉钉推送成功")
    except Exception as e:
        print(f"❌ 钉钉推送失败: {e}")


def main():
    print("=" * 48)
    print(f"Codex 重置监控  {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 48)

    body = fetch_json(API_STATUS)
    if "error" in body:
        print(f"❌ 获取状态失败: {body['error']}")
        send_bark(f"获取失败: {body['error']}")
        send_dingtalk(f"获取失败: {body['error']}")
        return

    data = body.get("data") or {}
    latest = data.get("latest_reset") or {}
    scheduled = data.get("scheduled_reset") or {}
    watch = data.get("active_watch") or {}
    stats = data.get("stats") or {}

    print(f"最近重置: {fmt_time(latest.get('announced_at'))}  {latest.get('reset_type')}")
    if scheduled:
        print(f"安排中: {fmt_time(scheduled.get('scheduled_for'))}  {scheduled.get('reset_type')}")
    if watch:
        print(f"观察: {watch.get('level')} chance={watch.get('reset_chance_percent')}")
    print(
        f"统计: 共 {stats.get('total')} 次 · "
        f"距上次 {stats.get('days_since_last')} 天 · "
        f"平均 {stats.get('avg_interval_days')} 天"
    )

    state = load_state()
    last_latest_id = state.get("last_latest_id") or ""
    last_scheduled_id = state.get("last_scheduled_id") or ""
    messages = []

    # 新的「已完成/已记录」重置
    latest_id = latest.get("id") or ""
    if latest_id and latest_id != last_latest_id:
        if last_latest_id:  # 首次只建基线
            messages.append(build_message(data, "latest", latest))
        else:
            print("📌 首次运行，记录当前最新重置作为基线")

    # 新的「安排中」重置
    scheduled_id = scheduled.get("id") or ""
    if scheduled_id and scheduled_id != last_scheduled_id:
        if last_latest_id:
            messages.append(build_message(data, "scheduled", scheduled))
        else:
            print("📌 首次运行，记录当前安排中的重置")

    save_state({
        "last_latest_id": latest_id,
        "last_scheduled_id": scheduled_id,
        "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
    })

    if not messages:
        print("✅ 无新的重置公告")
        return

    text = "\n\n---\n\n".join(messages)
    print("\n===== 通知 =====")
    print(text)
    print("================")
    send_bark(text)
    send_dingtalk(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        msg = f"{TITLE}\n\n脚本异常: {type(e).__name__}: {e}"
        print(msg)
        try:
            send_bark(msg)
            send_dingtalk(msg)
        except Exception:
            pass
        raise
