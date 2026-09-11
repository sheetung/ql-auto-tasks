# -*- coding: utf-8 -*-
"""
cron: */30 * * * *
new Env('华为新机监控');
name: 华为新机监控

三层信号（由早到晚）：
1. 发布会事件页（sitemap press/events，通常发布会前后出现）
2. 首页/手机页「热门产品」服务端直出链接（旗舰预热）
3. 产品页上架（sitemap phones，确认可购买/了解详情）
"""
import os
import re
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 推送配置（复用工程统一环境变量）
bark_push = os.environ.get("BARK_PUSH", "")
bark_push = f"https://api.day.app/{bark_push}" if bark_push and not bark_push.startswith("http") else bark_push
bark_group = "华为新机"
bark_icon = "https://consumer.huawei.com/etc/designs/huawei-cbg-site/clientlib-campaign-v4/common-v4/images/logo.svg"
bark_sound = os.environ.get("BARK_SOUND", "")
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

# 华为官网国内可直连，默认不走统一代理；仅在显式设置 HUAWEI_PROXY 时使用
try:
    from proxy_util import resolve_proxy, requests_proxies
except ImportError:
    def resolve_proxy(*names, use_unified=True, use_system=True):
        for name in names:
            v = os.environ.get(name) or os.environ.get(name.lower())
            if v:
                return v.strip()
        return ""

    def requests_proxies(proxy_url):
        if not proxy_url:
            return {}
        return {"http": proxy_url, "https": proxy_url}

huawei_proxy = resolve_proxy("HUAWEI_PROXY", use_unified=False, use_system=False)

SITEMAP_XML = "https://consumer.huawei.com/cn/sitemap.xml"
SITEMAP_HTML = "https://consumer.huawei.com/cn/sitemap/"
PHONES_PAGE = "https://consumer.huawei.com/cn/phones/"
PHONES_PREFIX = "/cn/phones/"
EVENTS_PREFIX = "/cn/press/events/"

STATE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(STATE_DIR, "huawei_phones_state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://consumer.huawei.com/cn/",
}

# 发布会 slug 关键词：只关心可能涉及手机/终端新品的活动
EVENT_PHONE_KEYWORDS = (
    "phone",
    "mate",
    "pura",
    "nova",
    "pocket",
    "xt",
    "all-scenario",
    "new-product",
    "launch",
    "fashion-gala",
    "harmonyos",
)


def make_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    proxies = requests_proxies(huawei_proxy)
    if proxies:
        session.proxies.update(proxies)
    return session


def is_phone_product_path(path):
    if not path.startswith(PHONES_PREFIX):
        return False
    rest = path[len(PHONES_PREFIX):].strip("/")
    if not rest or "/" in rest:
        return False
    skip = {
        "index.html", "index", "hicar", "hiplay",
        "switch-to-huawei", "phones",
    }
    return rest not in skip


def slug_to_name(slug):
    return slug.replace("-", " ").title()


def event_slug_to_title(slug):
    # 例如 huawei-mate-80-series-mate-x7-and-all-scenario-new-product-launch-event
    text = slug.replace("-", " ")
    return text.title()


def looks_like_phone_event(slug):
    low = slug.lower()
    return any(k in low for k in EVENT_PHONE_KEYWORDS)


def parse_sitemap(session):
    """一次解析 sitemap，同时返回 phones / events / phones_lastmod。"""
    resp = session.get(SITEMAP_XML, timeout=30)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    phones = {}
    events = {}
    phone_lastmod = {}

    for url_el in root.iter(f"{ns}url"):
        loc_el = url_el.find(f"{ns}loc")
        if loc_el is None or not loc_el.text:
            continue
        loc = loc_el.text.strip()
        lastmod_el = url_el.find(f"{ns}lastmod")
        lastmod = (lastmod_el.text or "").strip() if lastmod_el is not None else ""

        path = loc
        for prefix in (
            "https://consumer.huawei.com",
            "http://consumer.huawei.com",
        ):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break

        if is_phone_product_path(path):
            slug = path[len(PHONES_PREFIX):].strip("/")
            phones[slug] = {
                "slug": slug,
                "name": slug_to_name(slug),
                "url": f"https://consumer.huawei.com{path}",
                "lastmod": lastmod,
            }
            if lastmod:
                phone_lastmod[slug] = lastmod
            continue

        # 发布会路径形如 /cn/press/events/2026/<slug>/
        if path.startswith(EVENTS_PREFIX):
            rest = path[len(EVENTS_PREFIX):].strip("/")
            if not rest:
                continue
            parts = rest.split("/")
            # year/slug 或 仅 slug
            if len(parts) == 2 and parts[0].isdigit():
                year, slug = parts[0], parts[1]
            elif len(parts) == 1:
                year, slug = "", parts[0]
            else:
                continue
            if not looks_like_phone_event(slug):
                continue
            events[slug] = {
                "slug": slug,
                "year": year,
                "name": event_slug_to_title(slug),
                "url": f"https://consumer.huawei.com{path}",
                "lastmod": lastmod,
            }

    return phones, events, phone_lastmod


def enrich_phone_names(session, phones):
    try:
        resp = session.get(SITEMAP_HTML, timeout=30)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            path = href
            for prefix in (
                "https://consumer.huawei.com",
                "http://consumer.huawei.com",
            ):
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            if not is_phone_product_path(path):
                continue
            slug = path[len(PHONES_PREFIX):].strip("/")
            if slug in phones:
                name = a.get_text(" ", strip=True)
                if name and name not in ("了解更多", "购买", "详情"):
                    phones[slug]["name"] = name
    except Exception as e:
        print(f"⚠️ HTML 名称补全失败（不影响监控）: {e}")
    return phones


def fetch_hot_products(session):
    """手机页服务端直出的热门产品链接（通常是最新的 1-2 款旗舰）。"""
    hot = {}
    try:
        resp = session.get(PHONES_PAGE, timeout=30)
        resp.raise_for_status()
        hrefs = re.findall(
            r"""href=["'](/cn/phones/[a-z0-9\-]+/)["']""",
            resp.text,
            re.I,
        )
        for path in dict.fromkeys(hrefs):
            if not is_phone_product_path(path):
                continue
            slug = path[len(PHONES_PREFIX):].strip("/")
            hot[slug] = {
                "slug": slug,
                "name": slug_to_name(slug),
                "url": f"https://consumer.huawei.com{path}",
            }
        print(f"🔥 热门产品位 {len(hot)} 款: {', '.join(hot) or '无'}")
    except Exception as e:
        print(f"⚠️ 热门产品抓取失败（不影响主监控）: {e}")
    return hot


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧结构
        data.setdefault("phones", {})
        data.setdefault("events", {})
        data.setdefault("hot", {})
        data.setdefault("phone_lastmod", {})
        return data
    return {
        "phones": {},
        "events": {},
        "hot": {},
        "phone_lastmod": {},
        "updated_at": "",
    }


def save_state(state):
    data = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count_phones": len(state.get("phones", {})),
        "count_events": len(state.get("events", {})),
        "phones": state.get("phones", {}),
        "events": state.get("events", {}),
        "hot": state.get("hot", {}),
        "phone_lastmod": state.get("phone_lastmod", {}),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(
        f"💾 状态已保存: 手机 {data['count_phones']} / "
        f"发布会 {data['count_events']}"
    )


def diff_keys(old_map, new_map):
    added = [new_map[k] for k in new_map if k not in old_map]
    removed = [old_map[k] for k in old_map if k not in new_map]
    return added, removed


def build_changes(state, phones, events, hot):
    """汇总所有层的变动。"""
    changes = {
        "new_phones": [],
        "removed_phones": [],
        "new_events": [],
        "new_hot_not_listed": [],
    }

    old_phones = state.get("phones", {})
    added_p, removed_p = diff_keys(old_phones, phones)
    changes["new_phones"] = added_p
    changes["removed_phones"] = removed_p

    old_events = state.get("events", {})
    added_e, _ = diff_keys(old_events, events)
    changes["new_events"] = added_e

    # 热门位出现、但 sitemap 产品页还没有的型号 = 最早的预热信号
    for slug, info in hot.items():
        if slug not in phones and slug not in old_phones:
            changes["new_hot_not_listed"].append(info)

    return changes


def has_any_change(changes):
    return any(changes[k] for k in changes)


def send_bark(changes, total_phones):
    if not bark_push:
        print("未配置 Bark 推送，跳过")
        return

    lines = []
    if changes["new_events"]:
        lines.append(f"📣 新发布会/活动 {len(changes['new_events'])} 场：")
        for e in changes["new_events"]:
            lines.append(f"• {e['name']}")
            lines.append(f"  {e['url']}")
    if changes["new_hot_not_listed"]:
        lines.append(f"🔥 热门位新机（产品页可能未挂）：")
        for p in changes["new_hot_not_listed"]:
            lines.append(f"• {p['name']}  {p['url']}")
    if changes["new_phones"]:
        lines.append(f"🆕 产品页新增 {len(changes['new_phones'])} 款：")
        for p in changes["new_phones"]:
            lines.append(f"• {p['name']}")
            lines.append(f"  {p['url']}")
    if changes["removed_phones"]:
        lines.append(f"🗑️ 下架 {len(changes['removed_phones'])} 款：")
        for p in changes["removed_phones"]:
            lines.append(f"• {p.get('name', p.get('slug', ''))}")
    lines.append(f"\n当前官网共 {total_phones} 款手机")

    payload = {
        "title": "【autoTask】华为官网新机监控",
        "body": "\n".join(lines),
        "icon": bark_icon,
        "sound": bark_sound,
        "group": bark_group,
    }
    try:
        resp = requests.post(bark_push, json=payload, timeout=10)
        resp.raise_for_status()
        print("✅ Bark 推送成功")
    except Exception as e:
        print(f"❌ Bark 推送失败: {e}")


def send_dingtalk(changes, total_phones):
    if not dingtalk_token:
        print("未配置钉钉推送，跳过")
        return

    title = "【autoTask】华为官网新机监控"
    lines = [f"## {title}", ""]

    if changes["new_events"]:
        lines.append(f"### 📣 新发布会/活动 {len(changes['new_events'])} 场")
        for e in changes["new_events"]:
            lines.append(f"- **[{e['name']}]({e['url']})**")
        lines.append("")
    if changes["new_hot_not_listed"]:
        lines.append("### 🔥 热门位新机（产品页可能未挂）")
        for p in changes["new_hot_not_listed"]:
            lines.append(f"- **[{p['name']}]({p['url']})**")
        lines.append("")
    if changes["new_phones"]:
        lines.append(f"### 🆕 产品页新增 {len(changes['new_phones'])} 款")
        for p in changes["new_phones"]:
            lines.append(f"- **[{p['name']}]({p['url']})**")
        lines.append("")
    if changes["removed_phones"]:
        lines.append(f"### 🗑️ 下架 {len(changes['removed_phones'])} 款")
        for p in changes["removed_phones"]:
            lines.append(f"- {p.get('name', p.get('slug', ''))}")
        lines.append("")

    lines.append(f"> 当前官网共 **{total_phones}** 款手机")

    data = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": "\n".join(lines)},
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
        resp = requests.post(url, json=data, timeout=10)
        resp.raise_for_status()
        print("✅ 钉钉推送成功")
    except Exception as e:
        print(f"❌ 钉钉推送失败: {e}")


def main():
    print("=" * 48)
    print(f"华为官网新机监控  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 48)

    session = make_session()
    try:
        phones, events, phone_lastmod = parse_sitemap(session)
    except Exception as e:
        print(f"❌ sitemap 抓取失败: {e}")
        return

    if not phones:
        print("❌ sitemap 未解析到手机型号")
        return

    phones = enrich_phone_names(session, phones)
    hot = fetch_hot_products(session)

    print(f"✅ 产品页 {len(phones)} 款 | 发布会候选 {len(events)} 场")

    state = load_state()
    old_phones = state.get("phones", {})

    if not old_phones:
        print("📌 首次运行，建立三层基线")
        for p in sorted(phones.values(), key=lambda x: x["slug"]):
            print(f"   📱 {p['name']}  ({p['slug']})")
        if events:
            print("   近期发布会/活动：")
            for e in sorted(events.values(), key=lambda x: x.get("lastmod", ""), reverse=True)[:8]:
                print(f"   📣 {e.get('lastmod', '')[:10]}  {e['name']}")
        save_state({
            "phones": phones,
            "events": events,
            "hot": hot,
            "phone_lastmod": phone_lastmod,
        })
        return

    changes = build_changes(state, phones, events, hot)
    print(
        f"对比: 手机 {len(old_phones)}→{len(phones)} | "
        f"发布会 {len(state.get('events', {}))}→{len(events)}"
    )

    if not has_any_change(changes):
        print("✅ 今日无新增信号")
        save_state({
            "phones": phones,
            "events": events,
            "hot": hot,
            "phone_lastmod": phone_lastmod,
        })
        return

    if changes["new_events"]:
        print(f"\n📣 新发布会/活动 {len(changes['new_events'])} 场:")
        for e in changes["new_events"]:
            print(f"   + {e['name']}")
            print(f"     {e['url']}")
    if changes["new_hot_not_listed"]:
        print(f"\n🔥 热门位新机（产品页未挂）:")
        for p in changes["new_hot_not_listed"]:
            print(f"   + {p['name']}  {p['url']}")
    if changes["new_phones"]:
        print(f"\n🆕 产品页新增 {len(changes['new_phones'])} 款:")
        for p in changes["new_phones"]:
            print(f"   + {p['name']}")
            print(f"     {p['url']}")
    if changes["removed_phones"]:
        print(f"\n🗑️ 下架 {len(changes['removed_phones'])} 款:")
        for p in changes["removed_phones"]:
            print(f"   - {p.get('name', p.get('slug', ''))}")

    send_bark(changes, len(phones))
    send_dingtalk(changes, len(phones))
    save_state({
        "phones": phones,
        "events": events,
        "hot": hot,
        "phone_lastmod": phone_lastmod,
    })
    print("\n监控完成")


if __name__ == "__main__":
    main()
