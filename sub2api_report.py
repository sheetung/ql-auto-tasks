# -*- coding: utf-8 -*-
"""
cron: 0 22 * * *
new Env('sub2api日报');
name: sub2api日报
"""
import os
import hmac
import hashlib
import base64
import urllib.parse
import time
import json
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 推送
bark_push = os.environ.get("BARK_PUSH", "")
bark_push = f"https://api.day.app/{bark_push}" if bark_push and not bark_push.startswith("http") else bark_push
bark_group = "sub2api"
bark_icon = "https://www.svgrepo.com/show/354431/api.svg"
bark_sound = os.environ.get("BARK_SOUND", "")
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

# 代理：SUB2API_PROXY > AUTO_TASK_PROXY > 系统
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


sub2api_proxy = resolve_proxy("SUB2API_PROXY")
CST = timezone(timedelta(hours=8))
TITLE = "【autoTask】sub2api日报"
STATE_DIR = os.path.dirname(os.path.abspath(__file__))


def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({
        "Accept": "application/json",
        "User-Agent": "autoTask-sub2api-report/1.0",
    })
    if sub2api_proxy:
        s.proxies.update({"http": sub2api_proxy, "https": sub2api_proxy})
    return s


def parse_accounts():
    """SUB2API_ACCOUNTS="url@凭证&..."
    推荐: url@refresh_token   （rt_ 开头，无需 JWT，自动续期）
    也支持: url@jwt  或  url@jwt@refresh_token
    """
    accounts = []
    multi = os.environ.get("SUB2API_ACCOUNTS") or os.environ.get("sub2api_accounts") or ""
    if not multi:
        return accounts
    for item in multi.split("&"):
        item = item.strip()
        if not item or "@" not in item:
            continue
        if item.count("@") >= 2:
            url, token, refresh = item.rsplit("@", 2)
        else:
            url, token = item.rsplit("@", 1)
            refresh = ""
        url = url.strip().rstrip("/")
        token = token.strip()
        refresh = refresh.strip()
        # rt_ 开头：仅 refresh，无需预先 JWT
        if token.startswith("rt_") and not refresh:
            refresh = token
            token = ""
        if not url or (not token and not refresh):
            continue
        accounts.append((url, token, refresh))
    return accounts


def api_get(session, base, token, path, params=None):
    url = base + path
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = session.get(url, headers=headers, params=params or {}, timeout=30)
    except requests.RequestException as e:
        return {"error": f"请求失败: {type(e).__name__}: {e}"}
    if resp.status_code in (401, 403):
        return {"error": f"HTTP {resp.status_code}（Token 失效或无权限）", "auth_failed": True}
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        body = resp.json()
    except ValueError:
        return {"error": f"非 JSON 响应: {resp.text[:200]}"}
    if isinstance(body, dict) and "code" in body and body.get("code") not in (0, None, "0"):
        return {"error": body.get("message") or str(body)[:200]}
    return body


def _pick_token(body, *keys):
    if not isinstance(body, dict):
        return ""
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    for k in keys:
        v = data.get(k) or body.get(k)
        if v:
            return str(v).strip()
    return ""


def refresh_jwt(session, base, refresh_token):
    """POST /api/v1/auth/refresh → 新 JWT（及可能轮换的 refresh_token）。"""
    url = base + "/api/v1/auth/refresh"
    try:
        resp = session.post(
            url,
            json={"refresh_token": refresh_token},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        return {"error": f"refresh 请求失败: {type(e).__name__}: {e}"}

    if resp.status_code in (400, 401, 403):
        return {
            "error": f"refresh 失败 HTTP {resp.status_code}: {resp.text[:200]}",
            "auth_failed": True,
        }
    if resp.status_code >= 400:
        return {"error": f"refresh HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        body = resp.json()
    except ValueError:
        return {"error": f"refresh 非 JSON: {resp.text[:200]}"}
    if isinstance(body, dict) and "code" in body and body.get("code") not in (0, None, "0"):
        return {"error": body.get("message") or str(body)[:200]}

    access = _pick_token(body, "access_token", "accessToken", "token", "jwt", "access")
    if not access:
        return {"error": f"refresh 响应缺少 access_token: {str(body)[:200]}"}
    new_refresh = _pick_token(body, "refresh_token", "refreshToken", "refresh")
    return {"access_token": access, "refresh_token": new_refresh or refresh_token}


def fmt_tokens(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def fetch_today_usage(session, base, token, day_start, day_end, max_pages=20):
    """拉取当日用量明细并聚合。"""
    items = []
    page = 1
    while page <= max_pages:
        params = {
            "page": page,
            "page_size": 100,
            "start_time": day_start.isoformat(),
            "end_time": day_end.isoformat(),
        }
        body = api_get(session, base, token, "/api/v1/usage", params)
        if "error" in body:
            return None, body
        data = body.get("data") or {}
        batch = data.get("items") or []
        items.extend(batch)
        total = data.get("total")
        if not batch:
            break
        if total is not None and len(items) >= int(total):
            break
        if len(batch) < 100:
            break
        page += 1
    return items, None


def summarize_items(items):
    reqs = len(items)
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    total_tokens = 0
    cost = 0.0
    input_cost = 0.0
    output_cost = 0.0
    cache_cost = 0.0
    image_count = 0
    durations = []
    first_tokens = []
    models = {}
    endpoints = {}
    key_names = {}
    sessions = set()
    uas = {}
    efforts = {}
    stream_count = 0

    for it in items:
        input_tokens += it.get("input_tokens") or 0
        output_tokens += it.get("output_tokens") or 0
        cache_read += it.get("cache_read_tokens") or 0
        cache_creation += it.get("cache_creation_tokens") or 0
        total_tokens += it.get("total_tokens") or (
            (it.get("input_tokens") or 0)
            + (it.get("output_tokens") or 0)
            + (it.get("cache_read_tokens") or 0)
            + (it.get("cache_creation_tokens") or 0)
        )
        cost += it.get("actual_cost") or it.get("total_cost") or 0
        input_cost += it.get("input_cost") or 0
        output_cost += it.get("output_cost") or 0
        cache_cost += (it.get("cache_read_cost") or 0) + (it.get("cache_creation_cost") or 0)
        image_count += it.get("image_count") or 0
        if it.get("duration_ms"):
            durations.append(float(it["duration_ms"]))
        if it.get("first_token_ms"):
            first_tokens.append(float(it["first_token_ms"]))
        if it.get("stream"):
            stream_count += 1

        model = it.get("model") or "unknown"
        models[model] = models.get(model, 0) + 1
        ep = it.get("inbound_endpoint") or "unknown"
        endpoints[ep] = endpoints.get(ep, 0) + 1
        kn = (it.get("api_key") or {}).get("name") or f"id:{it.get('api_key_id')}"
        key_names[kn] = key_names.get(kn, 0) + 1
        sid = it.get("session_id")
        if sid:
            sessions.add(sid)
        ua = (it.get("user_agent") or "unknown")[:40]
        uas[ua] = uas.get(ua, 0) + 1
        effort = it.get("reasoning_effort") or "-"
        efforts[effort] = efforts.get(effort, 0) + 1

    def avg(seq):
        return sum(seq) / len(seq) if seq else 0.0

    def p95(seq):
        if not seq:
            return 0.0
        s = sorted(seq)
        idx = min(len(s) - 1, int(len(s) * 0.95))
        return s[idx]

    return {
        "requests": reqs,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "cache_tokens": cache_read + cache_creation,
        "total_tokens": total_tokens,
        "cost": cost,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "cache_cost": cache_cost,
        "image_count": image_count,
        "avg_duration_s": avg(durations) / 1000.0,
        "p95_duration_s": p95(durations) / 1000.0,
        "avg_first_token_s": avg(first_tokens) / 1000.0,
        "stream_count": stream_count,
        "session_count": len(sessions),
        "top_models": sorted(models.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_endpoints": sorted(endpoints.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_keys": sorted(key_names.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_uas": sorted(uas.items(), key=lambda x: x[1], reverse=True)[:3],
        "efforts": sorted(efforts.items(), key=lambda x: x[1], reverse=True)[:5],
    }


def summarize_keys(keys):
    rows = []
    for k in keys or []:
        rows.append({
            "name": k.get("name") or f"id:{k.get('id')}",
            "status": k.get("status") or "unknown",
            "usage_1d": k.get("usage_1d"),
            "usage_5h": k.get("usage_5h"),
            "usage_7d": k.get("usage_7d"),
            "rate_limit_1d": k.get("rate_limit_1d"),
            "rate_limit_5h": k.get("rate_limit_5h"),
            "rate_limit_7d": k.get("rate_limit_7d"),
            "current_concurrency": k.get("current_concurrency"),
            "quota": k.get("quota"),
            "quota_used": k.get("quota_used"),
            "last_used_at": k.get("last_used_at"),
        })
    return rows


def fmt_time(value):
    """ISO 时间 → 09-21 13:37，便于钉钉阅读。"""
    if not value:
        return "-"
    s = str(value)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(CST)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return s[:16].replace("T", " ")


def kv(label, value):
    return f"{label}｜{value}"


def build_report(base, profile, stats, daily, key_rows):
    """精简日报：余额 + 今日核心用量 + 模型摘要。"""
    email = profile.get("email") or f"uid:{profile.get('id')}"
    balance = profile.get("balance") or 0
    status = profile.get("status") or "unknown"

    L = [base]
    L.append(kv("账号", f"{email} [{status}]"))
    L.append(kv("余额", f"{balance:.2f}"))

    if daily:
        L.append(kv("今日", (
            f"{daily['requests']}次 · "
            f"{fmt_tokens(daily['total_tokens'])} · "
            f"花费 {daily['cost']:.2f}"
        )))
        L.append(kv("延迟", f"均 {daily['avg_duration_s']:.1f}s"))
        if daily["top_models"]:
            top = daily["top_models"][:2]
            L.append(kv("模型", "  ".join(f"{m}×{c}" for m, c in top)))
    else:
        L.append(kv("今日", "获取失败"))

    # 有配额限制的 Key 才提醒，避免刷屏
    limited = [
        k for k in (key_rows or [])
        if k.get("rate_limit_1d") or k.get("quota")
    ]
    if limited:
        for k in limited[:2]:
            if k.get("quota"):
                L.append(kv("Key", f"{k['name']} 配额 {k.get('quota_used')}/{k.get('quota')}"))

    return "\n".join(L)


def send_bark(text):
    if not bark_push:
        print("未配置 Bark 推送，跳过")
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
        print("未配置钉钉推送，跳过")
        return

    # 钉钉 Markdown 会吞掉单个换行，整段糊在一起。
    # 这里用 text 消息 + 逐行换行，保证可读。
    content = f"{TITLE}\n\n{text}"
    data = {
        "msgtype": "text",
        "text": {"content": content},
    }
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
    print(f"sub2api 日报  {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 48)

    accounts = parse_accounts()
    if not accounts:
        print("❌ 未配置账号。请设置 SUB2API_ACCOUNTS=\"url@token&url2@token2\"")
        return

    now = datetime.now(CST)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    session = make_session()
    reports = []

    for idx, (base, token, refresh) in enumerate(accounts, 1):
        print(f"\n➡️ 检查站点 {idx}: {base}")
        session = make_session()

        # 有 refresh_token 则先换新 JWT（约 24h 有效；接口会轮换 refresh_token）
        if refresh:
            # 优先使用上次轮换后保存的 RT，避免每天改青龙环境变量
            state_path = os.path.join(STATE_DIR, f"sub2api_refresh_{idx}.json")
            saved_rt = ""
            if os.path.exists(state_path):
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                    if saved.get("base") == base and saved.get("refresh_token"):
                        saved_rt = saved["refresh_token"]
                except (OSError, ValueError, json.JSONDecodeError):
                    saved_rt = ""
            use_rt = saved_rt or refresh
            if saved_rt:
                print("   （使用本地保存的 refresh_token）")

            print("   （refresh_token → 新 JWT）")
            rr = refresh_jwt(session, base, use_rt)
            if "error" in rr:
                # 本地 RT 失效时回退环境变量里的
                if saved_rt and use_rt == saved_rt and refresh != saved_rt:
                    print("   本地 RT 失效，尝试环境变量…")
                    rr = refresh_jwt(session, base, refresh)
            if "error" in rr:
                print(f"❌ {rr['error']}")
                reports.append(f"{base}\n状态｜❌ {rr['error']}")
                continue
            token = rr["access_token"]
            new_rt = rr.get("refresh_token") or use_rt
            if new_rt != use_rt or new_rt != refresh:
                try:
                    with open(state_path, "w", encoding="utf-8") as f:
                        json.dump({"base": base, "refresh_token": new_rt}, f, ensure_ascii=False, indent=2)
                    print(f"   refresh_token 已保存到 {os.path.basename(state_path)}")
                except OSError as e:
                    print(f"⚠️ 保存失败: {e}")
                if new_rt != refresh:
                    print("   可选：将青龙 SUB2API_ACCOUNTS 更新为最新 RT（不改也能靠本地文件续期）：")
                    print(f"   {base}@{new_rt}")
            print("   JWT 已刷新")

        if not token:
            print("❌ 无可用 JWT")
            reports.append(f"{base}\n状态｜❌ 无可用 JWT")
            continue

        profile_body = api_get(session, base, token, "/api/v1/user/profile")
        if "error" in profile_body:
            print(f"❌ 获取 profile 失败: {profile_body['error']}")
            reports.append(f"{base}\n状态｜❌ {profile_body['error']}")
            continue

        stats_body = api_get(session, base, token, "/api/v1/usage/stats")
        stats = None
        if "error" in stats_body:
            print(f"⚠️ 获取累计 stats 失败（不影响日报）: {stats_body['error']}")
        else:
            stats = (stats_body.get("data") or {}) if isinstance(stats_body, dict) else {}

        keys_body = api_get(session, base, token, "/api/v1/keys")
        key_rows = []
        if "error" in keys_body:
            print(f"⚠️ 获取 API Key 失败（不影响日报）: {keys_body['error']}")
        else:
            key_items = ((keys_body.get("data") or {}).get("items") or []) if isinstance(keys_body, dict) else []
            key_rows = summarize_keys(key_items)
            print(f"✅ API Key {len(key_rows)} 个")

        items, err = fetch_today_usage(session, base, token, day_start, day_end)
        if err:
            print(f"⚠️ 获取今日用量失败: {err.get('error')}")
            daily = None
        else:
            daily = summarize_items(items or [])
            print(
                f"✅ 今日 {daily['requests']} 次 · "
                f"{fmt_tokens(daily['total_tokens'])} · "
                f"花费 {daily['cost']:.2f}"
            )

        profile = profile_body.get("data") or {}
        print(f"✅ 余额 {profile.get('balance')}")
        reports.append(build_report(base, profile, stats, daily, key_rows))

    text = "\n\n---\n\n".join(reports)
    print("\n===== 日报内容 =====")
    print(text)
    print("====================")
    send_bark(text)
    send_dingtalk(text)
    print("\n日报推送完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        msg = f"{TITLE}\n\n脚本异常: {type(e).__name__}: {e}"
        print(f"❌ {msg}")
        try:
            send_bark(msg)
            send_dingtalk(msg)
        except Exception:
            pass
        raise
