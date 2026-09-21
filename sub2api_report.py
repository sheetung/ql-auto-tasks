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
    """只用 SUB2API_ACCOUNTS="url@token&url2@token2" """
    accounts = []
    multi = os.environ.get("SUB2API_ACCOUNTS") or os.environ.get("sub2api_accounts") or ""
    if not multi:
        return accounts
    for item in multi.split("&"):
        item = item.strip()
        if not item or "@" not in item:
            continue
        url, token = item.rsplit("@", 1)
        url = url.strip().rstrip("/")
        token = token.strip()
        if url and token:
            accounts.append((url, token))
    return accounts


def api_get(session, base, token, path, params=None):
    url = base + path
    headers = {"Authorization": f"Bearer {token}"}
    resp = session.get(url, headers=headers, params=params or {}, timeout=30)
    if resp.status_code in (401, 403):
        return {"error": f"HTTP {resp.status_code}（Token 失效或无权限）", "auth_failed": True}
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        body = resp.json()
    except ValueError:
        return {"error": f"非 JSON 响应: {resp.text[:200]}"}
    if isinstance(body, dict) and body.get("code") not in (0, None, "0"):
        return {"error": body.get("message") or str(body)[:200]}
    return body


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


def build_report(base, profile, stats, daily, key_rows):
    email = profile.get("email") or f"uid:{profile.get('id')}"
    balance = profile.get("balance") or 0
    frozen = profile.get("frozen_balance") or 0
    status = profile.get("status") or "unknown"
    recharged = profile.get("total_recharged") or 0
    last_active = profile.get("last_active_at") or "-"
    rpm_limit = profile.get("rpm_limit") or 0
    concurrency = profile.get("concurrency") or 0
    groups = profile.get("allowed_groups") or []

    lines = []
    lines.append(f"**站点**: {base}")
    lines.append(f"**账号**: {email}（{status}）")
    lines.append(f"**余额**: {balance:.4f}（冻结 {frozen:.4f}，累计充值 {recharged}）")
    lines.append(f"**最后活跃**: {last_active}")
    if rpm_limit or concurrency or groups:
        lines.append(
            f"**限制**: RPM {rpm_limit or '不限'} / 并发 {concurrency or '-'}"
            + (f" / 分组 {groups}" if groups else "")
        )
    lines.append("")

    if daily:
        lines.append("**今日用量**")
        lines.append(f"- 请求数: **{daily['requests']}**（流式 {daily['stream_count']}）")
        lines.append(
            f"- Tokens: 入 {fmt_tokens(daily['input_tokens'])} / "
            f"出 {fmt_tokens(daily['output_tokens'])} / "
            f"缓存读 {fmt_tokens(daily['cache_read'])} / "
            f"缓存写 {fmt_tokens(daily['cache_creation'])} / "
            f"合计 **{fmt_tokens(daily['total_tokens'])}**"
        )
        lines.append(
            f"- 花费: **{daily['cost']:.4f}**"
            f"（入 {daily['input_cost']:.4f} / 出 {daily['output_cost']:.4f}"
            f" / 缓存 {daily['cache_cost']:.4f}）"
        )
        lines.append(
            f"- 延迟: 平均 {daily['avg_duration_s']:.1f}s / "
            f"P95 {daily['p95_duration_s']:.1f}s / "
            f"首Token {daily['avg_first_token_s']:.1f}s"
        )
        lines.append(f"- 活跃会话: **{daily['session_count']}**")
        if daily.get("image_count"):
            lines.append(f"- 图像请求: {daily['image_count']}")
        if daily["top_models"]:
            lines.append("- 热门模型:")
            for m, c in daily["top_models"]:
                lines.append(f"  - `{m}` × {c}")
        if daily["top_endpoints"]:
            eps = ", ".join(f"`{e}`×{c}" for e, c in daily["top_endpoints"])
            lines.append(f"- 端点: {eps}")
        if daily["top_keys"]:
            keys_s = ", ".join(f"{n}×{c}" for n, c in daily["top_keys"])
            lines.append(f"- API Key: {keys_s}")
        if daily["efforts"]:
            efforts = ", ".join(f"{e}×{c}" for e, c in daily["efforts"])
            lines.append(f"- reasoning_effort: {efforts}")
        if daily["top_uas"]:
            uas = "; ".join(f"{u}×{c}" for u, c in daily["top_uas"])
            lines.append(f"- 客户端: {uas}")
        lines.append("")

    if key_rows:
        lines.append("**API Key 窗口**")
        for k in key_rows:
            quota = ""
            if k.get("quota"):
                quota = f" / 配额 {k.get('quota_used')}/{k.get('quota')}"
            limits = []
            for label, u, lim in (
                ("5h", k.get("usage_5h"), k.get("rate_limit_5h")),
                ("1d", k.get("usage_1d"), k.get("rate_limit_1d")),
                ("7d", k.get("usage_7d"), k.get("rate_limit_7d")),
            ):
                if u is None and lim is None:
                    continue
                u_s = "-" if u is None else u
                lim_s = "∞" if not lim else lim
                limits.append(f"{label} {u_s}/{lim_s}")
            lines.append(
                f"- `{k['name']}`（{k['status']}） "
                f"{' '.join(limits) if limits else '无窗口数据'}"
                f" / 并发 {k.get('current_concurrency') or 0}{quota}"
            )
            if k.get("last_used_at"):
                lines.append(f"  - 最后使用: {k['last_used_at']}")
        lines.append("")

    if stats:
        lines.append("**累计用量（接口 stats）**")
        lines.append(f"- 请求数: {stats.get('total_requests', 0)}")
        lines.append(
            f"- Tokens 合计: {fmt_tokens(stats.get('total_tokens'))}"
            f"（入 {fmt_tokens(stats.get('total_input_tokens'))}"
            f" / 出 {fmt_tokens(stats.get('total_output_tokens'))}"
            f" / 缓存 {fmt_tokens(stats.get('total_cache_tokens'))}）"
        )
        lines.append(f"- 累计花费: {float(stats.get('total_cost') or 0):.4f}")
        avg = stats.get("average_duration_ms")
        if avg:
            lines.append(f"- 平均耗时: {float(avg) / 1000:.1f}s")
        eps = stats.get("endpoints") or []
        if eps:
            parts = [
                f"`{e.get('endpoint')}` {e.get('requests')}次/{float(e.get('cost') or 0):.2f}"
                for e in eps[:5]
            ]
            lines.append(f"- 分端点: {', '.join(parts)}")

    return "\n".join(lines)


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
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": TITLE,
            "text": f"## {TITLE}\n\n{text}",
        },
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

    for idx, (base, token) in enumerate(accounts, 1):
        print(f"\n➡️ 检查站点 {idx}: {base}")
        profile_body = api_get(session, base, token, "/api/v1/user/profile")
        if "error" in profile_body:
            print(f"❌ 获取 profile 失败: {profile_body['error']}")
            reports.append(
                f"**站点**: {base}\n**状态**: ❌ {profile_body['error']}"
            )
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
                f"✅ 今日 {daily['requests']} 次请求，"
                f"花费 {daily['cost']:.4f}，"
                f"tokens {fmt_tokens(daily['total_tokens'])}，"
                f"平均 {daily['avg_duration_s']:.1f}s / "
                f"会话 {daily['session_count']}"
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
    main()
