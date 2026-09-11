# -*- coding: utf-8 -*-
"""
new Env('Wiley论文状态监控');
name: Wiley论文状态监控
cron: 35 * * * *
"""
import os
import json
import subprocess
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime

import requests

try:
    from proxy_util import resolve_proxy, apply_to_env
except ImportError:
    def resolve_proxy(*names, use_unified=True, use_system=True):
        for name in names:
            v = os.environ.get(name) or os.environ.get(name.lower())
            if v:
                return v.strip()
        if use_unified:
            v = os.environ.get("AUTO_TASK_PROXY") or os.environ.get("auto_task_proxy")
            if v:
                return v.strip()
        if use_system:
            for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
                v = os.environ.get(key)
                if v:
                    return v.strip()
        return ""

    def apply_to_env(env, proxy_url):
        if not proxy_url:
            return env
        env = dict(env)
        env["http_proxy"] = env["https_proxy"] = proxy_url
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = proxy_url
        return env

# 添加bark推送
bark_push = os.environ.get("BARK_PUSH", "")  # 填入你的 bark key 或完整 URL
bark_push = f"https://api.day.app/{bark_push}" if bark_push and not bark_push.startswith("http") else bark_push
bark_group = "Wiley"
bark_icon = "https://onlinelibrary.wiley.com/cover/doi/10.1002/(ISSN)1099-1239"
bark_sound = os.environ.get("BARK_SOUND", "")

# 添加钉钉推送
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

# 代理：WILEY_PROXY > AUTO_TASK_PROXY > 系统 https_proxy
wiley_proxy = resolve_proxy("WILEY_PROXY")

STATE_DIR = os.path.dirname(os.path.abspath(__file__))
# Cookie 失效提醒去重：同一账号 6 小时内不重复推送
COOKIE_ALERT_INTERVAL_SEC = 6 * 3600

COOKIE_REFRESH_GUIDE = """【如何更新 Cookie】
1. 浏览器打开并登录 https://authors.wiley.com/dashboard
2. F12 → Network → 刷新页面 → 点击任意请求
3. 复制 Request Headers 里的整段 Cookie
4. 更新青龙环境变量 WILEY_COOKIES（多账号用 & 分隔）"""


class WileyMonitor:
    name = "Wiley论文状态监控"

    def __init__(self, cookie):
        self.cookie = cookie
        self.api_url = "https://authors.wiley.com/dashboard/api/v2/cards"

    def fetch_cards(self):
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
        except ImportError:
            return self._fetch_cards_curl()

        session = requests.Session()
        retry = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.headers.update({
            "Content-Type": "application/json",
            "Referer": "https://authors.wiley.com/dashboard",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            "Cookie": self.cookie,
            "Accept": "application/json",
        })
        proxies = {}
        if wiley_proxy:
            proxies = {"http": wiley_proxy, "https": wiley_proxy}

        try:
            resp = session.get(
                self.api_url,
                timeout=30,
                allow_redirects=True,
                proxies=proxies or None,
            )
        except requests.Timeout:
            return {"error": "Request timeout", "cookie_expired": False}
        except requests.RequestException as e:
            return {"error": f"Network error: {e}", "cookie_expired": False}

        final_url = str(resp.url or "")
        content_type = (resp.headers.get("Content-Type") or "").lower()
        body_head = (resp.text or "")[:400].lower()

        # 登录失效常见表现：跳到 /dashboard/error、返回 HTML、401/403
        if resp.status_code in (401, 403):
            return {
                "error": f"HTTP {resp.status_code}（Cookie 失效或无权限）",
                "cookie_expired": True,
            }
        if "/dashboard/error" in final_url or "/login" in final_url:
            return {
                "error": "已跳转到登录/错误页（Cookie 失效）",
                "cookie_expired": True,
            }
        if "text/html" in content_type or body_head.startswith("<!doctype") or body_head.startswith("<html"):
            return {
                "error": "接口返回 HTML 而非 JSON（Cookie 失效或被拦截）",
                "cookie_expired": True,
            }
        if resp.status_code >= 400:
            return {
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                "cookie_expired": False,
            }

        try:
            return resp.json()
        except ValueError:
            return {
                "error": "响应不是合法 JSON（多半是 Cookie 失效）",
                "cookie_expired": True,
            }

    def _fetch_cards_curl(self):
        cmd = [
            "curl", "-s", "--http2", "-L",
            "-w", "\n__WILEY_HTTP_STATUS__:%{http_code}\n__WILEY_URL__:%{url_effective}",
            "-H", "Content-Type: application/json",
            "-H", "Referer: https://authors.wiley.com/dashboard",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "-H", f"Cookie: {self.cookie}",
            self.api_url,
        ]
        env = os.environ.copy()
        if wiley_proxy:
            env = apply_to_env(env, wiley_proxy)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
            if result.returncode != 0:
                return {"error": f"curl failed: {result.stderr}", "cookie_expired": False}

            stdout = result.stdout or ""
            http_status = 0
            final_url = ""
            body = stdout
            if "\n__WILEY_URL__:" in stdout:
                body, _, url_part = stdout.rpartition("\n__WILEY_URL__:")
                final_url = url_part.strip()
            if "\n__WILEY_HTTP_STATUS__:" in body:
                body, _, status_text = body.rpartition("\n__WILEY_HTTP_STATUS__:")
                if status_text.strip().isdigit():
                    http_status = int(status_text.strip())

            body_head = (body or "")[:400].lower()
            if http_status in (401, 403):
                return {
                    "error": f"HTTP {http_status}（Cookie 失效或无权限）",
                    "cookie_expired": True,
                }
            if "/dashboard/error" in final_url or "/login" in final_url:
                return {
                    "error": "已跳转到登录/错误页（Cookie 失效）",
                    "cookie_expired": True,
                }
            if body_head.startswith("<!doctype") or body_head.startswith("<html"):
                return {
                    "error": "接口返回 HTML 而非 JSON（Cookie 失效或被拦截）",
                    "cookie_expired": True,
                }
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {
                    "error": "响应不是合法 JSON（多半是 Cookie 失效）",
                    "cookie_expired": True,
                }
        except subprocess.TimeoutExpired:
            return {"error": "Request timeout", "cookie_expired": False}


def _cookie_alert_path(account_index):
    return os.path.join(STATE_DIR, f"wiley_cookie_alert_{account_index}.json")


def should_notify_cookie_expired(account_index):
    """去重：距上次失效提醒不足 N 小时则跳过。"""
    path = _cookie_alert_path(account_index)
    now = time.time()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            last = float(data.get("last_notified_at", 0))
            if now - last < COOKIE_ALERT_INTERVAL_SEC:
                return False
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    return True


def mark_cookie_alerted(account_index):
    path = _cookie_alert_path(account_index)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_notified_at": time.time()}, f)


def clear_cookie_alert(account_index):
    path = _cookie_alert_path(account_index)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def send_cookie_expired_bark(account_index, error):
    if not bark_push:
        print("未配置 Bark，跳过 Cookie 失效推送")
        return

    body = (
        f"账号 {account_index} Wiley Cookie 已失效，请立即更新 WILEY_COOKIES。\n\n"
        f"原因：{error}\n\n"
        f"{COOKIE_REFRESH_GUIDE}"
    )
    payload = {
        "title": "【autoTask】Wiley Cookie 失效，请更新",
        "body": body,
        "icon": bark_icon,
        "sound": bark_sound or "alarm",
        "group": bark_group,
        "level": "timeSensitive",
    }
    try:
        resp = requests.post(bark_push, json=payload, timeout=10)
        resp.raise_for_status()
        print("✅ Bark Cookie 失效提醒已发送")
    except Exception as e:
        print(f"❌ Bark Cookie 失效提醒失败: {e}")


def send_cookie_expired_dingtalk(account_index, error):
    if not dingtalk_token:
        print("未配置钉钉，跳过 Cookie 失效推送")
        return

    title = "【autoTask】Wiley Cookie 失效，请更新"
    text = (
        f"## {title}\n\n"
        f"账号 **{account_index}** 的 Wiley Cookie 已失效，请立即更新 `WILEY_COOKIES`。\n\n"
        f"**原因**：{error}\n\n"
        f"### 更新步骤\n"
        f"1. 登录 https://authors.wiley.com/dashboard\n"
        f"2. F12 → Network → 刷新 → 复制请求头 Cookie\n"
        f"3. 更新青龙环境变量 `WILEY_COOKIES`\n\n"
        f"> 6 小时内不会重复提醒；恢复后会自动继续监控。"
    )
    data = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    if dingtalk_secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{dingtalk_secret}"
        sign = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(dingtalk_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
        ))
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}&timestamp={timestamp}&sign={sign}"
    else:
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}"

    try:
        resp = requests.post(dingtalk_url, json=data, timeout=10)
        resp.raise_for_status()
        print("✅ 钉钉 Cookie 失效提醒已发送")
    except Exception as e:
        print(f"❌ 钉钉 Cookie 失效提醒失败: {e}")


def notify_cookie_expired(account_index, error):
    """检测到 Cookie 失效时立刻推送（带去重）。"""
    if not should_notify_cookie_expired(account_index):
        print(f"账号 {account_index} 失效提醒已发过（{COOKIE_ALERT_INTERVAL_SEC // 3600}h 内不重复）")
        return False
    print(f"🚨 账号 {account_index} Cookie 失效，立即推送提醒")
    send_cookie_expired_bark(account_index, error)
    send_cookie_expired_dingtalk(account_index, error)
    mark_cookie_alerted(account_index)
    return True


def get_state_file(account_index):
    return os.path.join(STATE_DIR, f"wiley_state_{account_index}.json")


def load_state(account_index):
    path = get_state_file(account_index)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(account_index, state):
    path = get_state_file(account_index)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def extract_submission_info(card):
    title = card.get("title", {}).get("text", "未知标题")
    state = card.get("cardState", {})
    status_name = state.get("name", "未知")
    status_value = state.get("status", "")
    manuscript_id = card.get("manuscriptId", "")
    submission_id = card.get("submissionId", "")
    modified_at = card.get("modifiedAt", "")

    # 提取日期信息
    dates = []
    for d in card.get("dates", []):
        label = d.get("label", "")
        date_vars = d.get("dateValue", {}).get("variables", [])
        date_str = ""
        by_str = ""
        for var in date_vars:
            if var.get("type") == "date-time" and var.get("value"):
                date_str = var["value"]
        # 从 text 模板中提取 by 谁
        text_template = d.get("dateValue", {}).get("text", "")
        if "by " in text_template:
            by_str = text_template.split("by ")[-1]
        dates.append({"label": label, "date": date_str, "by": by_str})

    # 提取通知信息
    notifications = []
    for n in card.get("notifications", []):
        msg = n.get("message", {}).get("text", "")
        if msg:
            notifications.append(msg)

    return {
        "title": title,
        "status": status_name,
        "status_value": status_value,
        "manuscript_id": manuscript_id,
        "submission_id": submission_id,
        "modified_at": modified_at,
        "dates": dates,
        "notifications": notifications,
    }


def detect_changes(old_state, new_cards):
    changes = []
    new_state = {}

    for card in new_cards:
        info = extract_submission_info(card)
        sid = info["submission_id"]
        new_state[sid] = info

        if sid not in old_state:
            changes.append({
                "type": "new",
                "title": info["title"],
                "manuscript_id": info["manuscript_id"],
                "status": info["status"],
                "detail": f"新投稿: {info['title']}",
            })
            continue

        old_info = old_state[sid]

        # 检查状态变化
        if old_info.get("status") != info["status"]:
            changes.append({
                "type": "status_change",
                "title": info["title"],
                "manuscript_id": info["manuscript_id"],
                "old_status": old_info.get("status", "未知"),
                "new_status": info["status"],
                "detail": f"状态变更: {info['title']} [{old_info.get('status', '未知')} -> {info['status']}]",
            })

        # 检查通知变化
        old_notifications = set(old_info.get("notifications", []))
        new_notifications = set(info.get("notifications", []))
        added = new_notifications - old_notifications
        if added:
            for msg in added:
                changes.append({
                    "type": "notification",
                    "title": info["title"],
                    "manuscript_id": info["manuscript_id"],
                    "status": info["status"],
                    "detail": f"新通知 [{info['title']}]: {msg}",
                })

        # 检查日期变化（新增了日期条目说明有新事件）
        old_date_count = len(old_info.get("dates", []))
        new_date_count = len(info.get("dates", []))
        if new_date_count > old_date_count:
            new_dates = info["dates"][old_date_count:]
            for d in new_dates:
                changes.append({
                    "type": "date_event",
                    "title": info["title"],
                    "manuscript_id": info["manuscript_id"],
                    "detail": f"新事件 [{info['title']}]: {d['label']} {d['date']} by {d['by']}",
                })

    # 检查删除的投稿
    for sid in old_state:
        if sid not in new_state:
            changes.append({
                "type": "removed",
                "title": old_state[sid].get("title", "未知"),
                "detail": f"投稿已移除: {old_state[sid].get('title', '未知')}",
            })

    return changes, new_state


def format_status_emoji(status):
    mapping = {
        "Published": "🎉",
        "Under Review": "🔍",
        "In Revision": "📝",
        "Rejected": "❌",
        "Accepted": "✅",
        "Submitted": "📤",
    }
    return mapping.get(status, "📄")


def send_bark_notification(changes, all_submissions):
    if not bark_push:
        print("未配置Bark推送，跳过通知")
        return

    if not changes:
        print("无变动，跳过Bark通知")
        return

    title = "【autoTask】Wiley论文状态变动"
    body_lines = []
    for change in changes:
        body_lines.append(change["detail"])
    body = "\n".join(body_lines)

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": bark_icon,
        "sound": bark_sound,
        "group": bark_group,
    }, ensure_ascii=False)

    cmd = ["curl", "-s", "-X", "POST", bark_push, "-H", "Content-Type: application/json", "-d", payload]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print("✅ Bark推送成功" if result.returncode == 0 else f"❌ Bark推送失败: {result.stderr}")
    except Exception as e:
        print(f"❌ Bark推送失败: {str(e)}")


def send_dingtalk_notification(changes, all_submissions):
    if not dingtalk_token:
        print("未配置钉钉推送，跳过通知")
        return

    if not changes:
        print("无变动，跳过钉钉通知")
        return

    title = "【autoTask】Wiley论文状态变动"
    text_lines = [f"## {title}", ""]

    for change in changes:
        emoji = "🆕" if change["type"] == "new" else "🔄" if change["type"] == "status_change" else "🔔" if change["type"] == "notification" else "📅" if change["type"] == "date_event" else "🗑️"
        text_lines.append(f"- {emoji} {change['detail']}")

    text_lines.append("")
    text_lines.append("---")
    text_lines.append("### 当前投稿概览")
    text_lines.append("")
    for sub in all_submissions:
        status = sub["status"]
        text_lines.append(f"{sub['manuscript_id']} | {sub['title'][:35]}... | **{status}**")

    text = "\n".join(text_lines)

    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
    }

    if dingtalk_secret:
        timestamp = str(round(time.time() * 1000))
        secret_enc = dingtalk_secret.encode("utf-8")
        string_to_sign = "{}\n{}".format(timestamp, dingtalk_secret)
        string_to_sign_enc = string_to_sign.encode("utf-8")
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}&timestamp={timestamp}&sign={sign}"
    else:
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}"

    payload = json.dumps(data, ensure_ascii=False)
    cmd = ["curl", "-s", "-X", "POST", dingtalk_url, "-H", "Content-Type: application/json; charset=utf-8", "-d", payload]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print(f"钉钉响应：{result.stdout}")
        print("✅ 钉钉推送成功" if result.returncode == 0 else f"❌ 钉钉推送失败")
    except Exception as e:
        print(f"❌ 钉钉推送失败: {str(e)}")


def main():
    cookies = os.getenv("WILEY_COOKIES")
    if not cookies:
        print("未找到环境变量 WILEY_COOKIES，请检查配置")
        return

    cookie_list = cookies.split("&")
    all_results = []

    for i, cookie in enumerate(cookie_list):
        print(f"正在检查第 {i + 1} 个账号...")
        monitor = WileyMonitor(cookie)
        data = monitor.fetch_cards()

        if "error" in data:
            print(f"第 {i + 1} 个账号获取数据失败: {data['error']}")
            if data.get("cookie_expired"):
                notify_cookie_expired(i + 1, data["error"])
            all_results.append({
                "status": "error",
                "error": data["error"],
                "cookie_expired": data.get("cookie_expired", False),
            })
            continue

        # Cookie 恢复：清除失效提醒标记
        clear_cookie_alert(i + 1)

        cards = data.get("content", [])
        if not isinstance(cards, list):
            cards = []
        print(f"获取到 {len(cards)} 篇投稿")

        # 加载旧状态（按账号分开存储）
        old_state = load_state(i)

        # 检测变化
        changes, new_state = detect_changes(old_state, cards)

        # 提取所有投稿信息
        all_submissions = [extract_submission_info(card) for card in cards]

        if changes:
            print(f"\n检测到 {len(changes)} 个变动:")
            for change in changes:
                print(f"  - {change['detail']}")
        else:
            print("无变动")

        # 保存新状态
        save_state(i, new_state)

        # 发送通知
        send_bark_notification(changes, all_submissions)
        send_dingtalk_notification(changes, all_submissions)

        all_results.append({
            "status": "success",
            "changes": changes,
            "submissions": all_submissions,
        })
        print(f"第 {i + 1} 个账号检查完成\n")

    # 打印汇总
    print("\n检查结果汇总：")
    for idx, result in enumerate(all_results, 1):
        if result["status"] == "success":
            changes = result["changes"]
            subs = result["submissions"]
            print(f"账号{idx}: 获取 {len(subs)} 篇投稿, {len(changes)} 个变动")
            for sub in subs:
                emoji = format_status_emoji(sub["status"])
                print(f"  {emoji} [{sub['status']}] {sub['manuscript_id']}: {sub['title']}")
        else:
            print(f"账号{idx}: 获取失败 - {result['error']}")


if __name__ == "__main__":
    main()
