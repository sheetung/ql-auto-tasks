# -*- coding: utf-8 -*-
"""
new Env('NewAPI签到');
name: NewAPI签到
cron: 0 0 * * *
"""
import os
import json
import requests
import time
import hmac
import hashlib
import base64
import urllib.parse
import re
from datetime import datetime

# 添加bark推送
bark_push = os.environ.get("BARK_PUSH", "")
bark_push = f"https://api.day.app/{bark_push}" if bark_push and not bark_push.startswith("http") else bark_push
bark_group = "NewAPI"
bark_icon = "https://staticres.ablesci.com/apple-touch-icon.png"
bark_sound = os.environ.get("BARK_SOUND", "")

# 添加钉钉推送
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

class NewAPI:
    name = "NewAPI签到"

    def __init__(self, url, credential, session=None):
        self.url = url.rstrip('/')
        self.credential = credential.strip()
        self.session = session or requests.Session()

    @staticmethod
    def _is_success_response(data):
        """兼容不同 NewAPI 版本的签到返回格式。"""
        if not isinstance(data, dict):
            return False

        message = str(data.get("message", data.get("msg", "")))
        message_lower = message.lower()
        already_checked_keywords = ("已经签到", "已签到", "重复签到", "already checked", "already signed")
        success_keywords = ("签到成功", "check-in successful", "success")

        if any(keyword in message_lower for keyword in already_checked_keywords):
            return True
        if data.get("success") is True or data.get("ret") == 1 or data.get("code") == 0:
            return True
        return any(keyword in message_lower for keyword in success_keywords)

    @staticmethod
    def _response_message(data):
        if isinstance(data, dict):
            return str(data.get("message", data.get("msg", data.get("error", "未知错误"))))
        return "响应格式错误"

    @staticmethod
    def _decode_jwt_payload(token):
        """仅解析 JWT 元数据用于提示，不验证也不输出凭证。"""
        parts = token.split(".")
        if len(parts) != 3:
            return None
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _credential_config(self):
        """生成新版面板 PAT 鉴权配置。"""
        credential = self.credential
        lowered = credential.lower()

        if lowered.startswith("cookie:") or lowered.startswith("cookie=") or "session=" in lowered:
            return (
                "cookie",
                {},
                "新版 New API 已不支持旧 session Cookie，请改用个人设置中的面板访问令牌 PAT",
            )

        if lowered.startswith("authorization:") or lowered.startswith("authorization="):
            value = credential.split(credential[13], 1)[1].strip()
        elif lowered.startswith("pat:") or lowered.startswith("pat="):
            value = credential[4:].strip()
        elif lowered.startswith("bearer "):
            value = credential
        else:
            value = credential

        if not value:
            return "pat", {}, "认证凭据为空"

        token = value[7:].strip() if value.lower().startswith("bearer ") else value
        jwt_payload = self._decode_jwt_payload(token)
        if jwt_payload and jwt_payload.get("token_use") == "access":
            exp = jwt_payload.get("exp")
            expiry = ""
            if isinstance(exp, (int, float)):
                expiry = datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S")
                expiry = f"（到期时间 {expiry}）"
            return (
                "browser_access_token",
                {},
                "检测到浏览器短期 Access Token"
                f"{expiry}，它通常仅有效 15 分钟，不能用于定时任务；"
                "请改用个人设置中的面板访问令牌 PAT（User.AccessToken）",
            )

        return "pat", {"Authorization": f"Bearer {token}"}, None

    @staticmethod
    def _is_cloudflare_page(response):
        content_type = response.headers.get("Content-Type", "").lower()
        text = response.text.lower()
        return "text/html" in content_type and (
            "just a moment" in text
            or "cf-chl-" in text
            or "challenge-platform" in text
        )

    @classmethod
    def _read_json(cls, response):
        if cls._is_cloudflare_page(response):
            raise RuntimeError("遇到 Cloudflare 人机验证，请先在浏览器完成验证")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"服务端返回非 JSON 内容（HTTP {response.status_code}）"
            ) from exc

    def sign(self):
        # 签到URL，根据NewAPI站点的实际签到接口调整
        # 从测试结果看，正确的接口路径是 /api/user/checkin
        sign_url = f"{self.url}/api/user/checkin"
        
        # 基础头部
        base_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "DNT": "1",
            "Referer": f"{self.url}/",
            "Origin": self.url,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        # 读取代理：NEWAPI_PROXY > AUTO_TASK_PROXY > 系统 https_proxy
        try:
            from proxy_util import resolve_proxy, requests_proxies
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

            def requests_proxies(proxy_url):
                if not proxy_url:
                    return {}
                return {"http": proxy_url, "https": proxy_url}

        proxies = requests_proxies(resolve_proxy("NEWAPI_PROXY"))

        if proxies:
            print(f"使用代理: {proxies}")
        
        auth_type, credential_headers, credential_error = self._credential_config()
        if credential_error:
            return {"status": "error", "message": f"签到失败: {credential_error}"}

        headers = dict(base_headers, **credential_headers)
        print("尝试认证方式: 面板 PAT")

        try:
            response = self.session.post(
                sign_url, headers=headers, proxies=proxies, timeout=30
            )
            result = self._read_json(response)

            if not 200 <= response.status_code < 300:
                message = self._response_message(result)
                return {
                    "status": "error",
                    "message": f"签到失败: HTTP {response.status_code}: {message}",
                }

            if not self._is_success_response(result):
                message = self._response_message(result)
                code = result.get("code") if isinstance(result, dict) else None
                suffix = f" [{code}]" if code else ""
                return {"status": "error", "message": f"签到失败: {message}{suffix}"}

            # 签到成功或今日已签到后，尽量拉取当月统计；失败不影响签到结果。
            try:
                detail_response = self.session.get(
                    sign_url, headers=headers, proxies=proxies, timeout=30
                )
                if 200 <= detail_response.status_code < 300:
                    detail_result = self._read_json(detail_response)
                    if isinstance(detail_result, dict):
                        result["detail"] = detail_result
            except (requests.exceptions.RequestException, RuntimeError) as exc:
                print(f"获取签到详情失败: {exc}")

            return {"status": "success", "message": "签到成功", "data": result}
        except requests.exceptions.RequestException as exc:
            return {"status": "error", "message": f"签到失败: 网络请求异常: {exc}"}
        except RuntimeError as exc:
            return {"status": "error", "message": f"签到失败: {exc}"}

    def main(self):
        print(f"正在签到站点: {self.url}")
        auth_type, _, _ = self._credential_config()
        credential_type = {
            "pat": "面板 PAT",
            "cookie": "旧版 Cookie（不支持）",
            "browser_access_token": "浏览器短期 Access Token（不可用于定时任务）",
        }.get(auth_type, "未知")
        print(f"使用认证方式: {credential_type}")
        result = self.sign()

        if result.get('data'):
            details = parse_sign_details(result)
            print(f"签到结果: {details['msg']}")
            print(f"今日配额: {format_quota(details['today_quota'])} 配额 (${format_quota_usd(details['today_quota'])})")
            print(f"累计签到: {details['total_checkins']} 天")
            print(f"累计配额: {format_quota(details['total_quota'])} 配额 (${format_quota_usd(details['total_quota'])})")

            detail_data = result['data'].get('detail', {}).get('data', {})
            records = detail_data.get('stats', {}).get('records', [])
            if records:
                print("最近签到记录:")
                for record in records:
                    日期 = record.get('checkin_date', '未知')
                    获得配额 = record.get('quota_awarded') or 0
                    print(f"  - {日期}: {format_quota(获得配额)} 配额 (${format_quota_usd(获得配额)})")
        else:
            print(f"签到结果: {result}")

        return result


def format_quota(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)

def format_quota_usd(value):
    try:
        return f"{float(value) / 500000:.4f}"
    except (TypeError, ValueError):
        return "0.0000"

def parse_sign_details(result):
    """解析签到详细信息"""
    details = {
        "msg": "签到成功",
        "total_checkins": 0,
        "total_quota": 0,
        "today_quota": 0,
        "is_already_checked": False
    }

    data = result.get('data', {})
    details['msg'] = data.get('message', '签到成功')
    checkin_data = data.get('data', {}) if isinstance(data.get('data'), dict) else {}
    details['today_quota'] = checkin_data.get('quota_awarded') or 0
    message = str(details['msg'])
    details['is_already_checked'] = (
        data.get('success') is False or
        '\u5df2\u7b7e\u5230' in message or
        '\u5df2\u7ecf\u7b7e\u5230' in message
    )

    detail = data.get('detail', {})
    if detail.get('data'):
        stats = detail['data'].get('stats', {})
        records = stats.get('records', [])
        valid_records = [record for record in records if isinstance(record, dict)]

        if valid_records:
            details['total_checkins'] = len(valid_records)
            details['total_quota'] = sum(
                (record.get('quota_awarded') or 0) for record in valid_records
            )

            today_str = datetime.now().strftime("%Y-%m-%d")
            today_record = next(
                (record for record in valid_records if str(record.get('checkin_date', '')).startswith(today_str)),
                None
            )
            latest_record = valid_records[0]
            current_record = today_record or latest_record
            details['today_quota'] = current_record.get('quota_awarded') or details['today_quota']
        else:
            details['total_checkins'] = stats.get('total_checkins', 0)

        if stats.get('checkin_today'):
            details['is_already_checked'] = True

    return details


def load_newapi_accounts(env=None):
    """读取账号配置；JSON 格式优先，并兼容旧的 @/& 格式。"""
    env = os.environ if env is None else env
    json_value = env.get("NEWAPI_ACCOUNTS_JSON", "").strip()
    if json_value:
        try:
            raw_accounts = json.loads(json_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NEWAPI_ACCOUNTS_JSON 不是合法 JSON: {exc}") from exc
        if not isinstance(raw_accounts, list):
            raise ValueError("NEWAPI_ACCOUNTS_JSON 顶层必须是数组")

        accounts = []
        for index, item in enumerate(raw_accounts, 1):
            if not isinstance(item, dict):
                raise ValueError(f"NEWAPI_ACCOUNTS_JSON 第 {index} 项必须是对象")
            url = str(item.get("url", "")).strip()
            credential = str(
                item.get("pat")
                or item.get("credential")
                or item.get("token")
                or ""
            ).strip()
            if not url or not credential:
                raise ValueError(f"NEWAPI_ACCOUNTS_JSON 第 {index} 项缺少 url 或 pat/credential")
            accounts.append({
                "url": url,
                "credential": credential,
            })
        return accounts

    legacy_value = env.get("NEWAPI_ACCOUNTS", "").strip()
    if not legacy_value:
        return []

    # 仅在下一个 http(s) 账号开始处切分，PAT 内即使含有 & 也不会被误拆。
    entries = re.split(r"&(?=https?://)", legacy_value)
    accounts = []
    for index, entry in enumerate(entries, 1):
        parts = entry.split("@", 1)
        if len(parts) != 2:
            raise ValueError(f"NEWAPI_ACCOUNTS 第 {index} 项格式错误，应为 url@PAT")
        url, credential = parts
        if not url.strip() or not credential.strip():
            raise ValueError(f"NEWAPI_ACCOUNTS 第 {index} 项缺少 URL 或凭据")
        accounts.append({
            "url": url.strip(),
            "credential": credential.strip(),
        })
    return accounts


def send_bark_notification(results):
    if not bark_push:
        print("未配置Bark推送，跳过通知")
        return

    title = "【autoTask】NewAPI签到"
    body_lines = []

    for idx, (url, result) in enumerate(results, 1):
        if result.get('status') == 'success':
            details = parse_sign_details(result)
            site_name = url.replace('https://', '').replace('http://', '').split('/')[0]

            if details['is_already_checked']:
                body_lines.append(
                    f"{site_name}: 今日已签到 | 累计{details['total_checkins']}天 | "
                    f"今日{format_quota(details['today_quota'])}配额(${format_quota_usd(details['today_quota'])}) | "
                    f"累计{format_quota(details['total_quota'])}配额(${format_quota_usd(details['total_quota'])})"
                )
            else:
                body_lines.append(
                    f"{site_name}: 签到成功 | 今日+{format_quota(details['today_quota'])}配额(${format_quota_usd(details['today_quota'])}) | "
                    f"累计{details['total_checkins']}天 | 累计{format_quota(details['total_quota'])}配额(${format_quota_usd(details['total_quota'])})"
                )
        else:
            error = result.get('message', '未知错误')
            site_name = url.replace('https://', '').replace('http://', '').split('/')[0] if url else f"站点{idx}"
            body_lines.append(f"{site_name}: ❌签到失败 - {error}")

    body = "\n".join(body_lines)

    # 构造Bark请求参数
    params = {
        'title': title,
        'body': body,
        'icon': bark_icon,
        'sound': bark_sound,
        'group': bark_group
    }

    # 发送POST请求（JSON格式）
    bark_url = f"{bark_push}"
    try:
        resp = requests.post(bark_url, json=params)
        resp.raise_for_status()
        print("✅ Bark推送成功")
    except Exception as e:
        print(f"❌ Bark推送失败: {str(e)}")

def send_dingtalk_notification(results):
    if not dingtalk_token:
        print("未配置钉钉推送，跳过通知")
        return

    title = "【autoTask】NewAPI签到"
    text_lines = []
    text_lines.append(f"## {title}")
    text_lines.append("")

    success_count = 0
    fail_count = 0

    for idx, (url, result) in enumerate(results, 1):
        if result.get('status') == 'success':
            details = parse_sign_details(result)
            site_name = url.replace('https://', '').replace('http://', '').split('/')[0]

            if details['is_already_checked']:
                text_lines.append(
                    f"**站点{idx}**: {site_name}\n"
                    f"- 状态: 今日已签到\n"
                    f"- 今日配额: {format_quota(details['today_quota'])} 配额 (${format_quota_usd(details['today_quota'])})\n"
                    f"- 累计签到: {details['total_checkins']} 天\n"
                    f"- 累计配额: {format_quota(details['total_quota'])} 配额 (${format_quota_usd(details['total_quota'])})\n"
                )
            else:
                text_lines.append(
                    f"**站点{idx}**: {site_name}\n"
                    f"- 状态: 签到成功\n"
                    f"- 今日配额: {format_quota(details['today_quota'])} 配额 (${format_quota_usd(details['today_quota'])})\n"
                    f"- 累计签到: {details['total_checkins']} 天\n"
                    f"- 累计配额: {format_quota(details['total_quota'])} 配额 (${format_quota_usd(details['total_quota'])})\n"
                )
            success_count += 1
        else:
            error = result.get('message', '未知错误')
            site_name = url.replace('https://', '').replace('http://', '').split('/')[0] if url else f"站点{idx}"
            text_lines.append(
                f"**站点{idx}**: {site_name}\n"
                f"- 状态: ❌ 签到失败\n"
                f"- 原因: {error}\n"
            )
            fail_count += 1

    text_lines.append("---")
    text_lines.append(f"**汇总**: 成功 {success_count} 个，失败 {fail_count} 个")

    text = "\n".join(text_lines)

    # 构造钉钉消息体
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text
        }
    }

    # 签名验证
    if dingtalk_secret:
        timestamp = str(round(time.time() * 1000))
        secret_enc = dingtalk_secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, dingtalk_secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}&timestamp={timestamp}&sign={sign}"
    else:
        dingtalk_url = f"https://oapi.dingtalk.com/robot/send?access_token={dingtalk_token}"

    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        resp = requests.post(dingtalk_url, json=data, headers=headers)
        print(f"钉钉响应：{resp.text}")
        resp.raise_for_status()
        print("✅ 钉钉推送成功")
    except requests.exceptions.HTTPError as e:
        print(f"❌ 钉钉推送失败: {e}")
        print(f"错误详情: {resp.text}")
    except Exception as e:
        print(f"❌ 钉钉推送失败: {str(e)}")

def main():
    try:
        accounts = load_newapi_accounts()
    except ValueError as exc:
        print(f"NewAPI 账号配置错误: {exc}")
        return

    if not accounts:
        print("未找到 NEWAPI_ACCOUNTS_JSON 或 NEWAPI_ACCOUNTS，请检查配置")
        return
    
    results = []
    
    for i, account in enumerate(accounts):
        print(f"正在签到第 {i + 1} 个站点...")
        try:
            url = account["url"]
            result = NewAPI(
                url,
                account["credential"],
            ).main()
            results.append((url, result))
        except Exception as e:
            results.append(("", {"status": "error", "message": f"第 {i + 1} 个站点签到失败: {str(e)}"}))
        print(f"第 {i + 1} 个站点签到完成\n")

    print("\n签到结果汇总：")
    for url, result in results:
        print(f"站点: {url}")
        print(f"结果: {result}")
        print()

    # 发送Bark通知
    send_bark_notification(results)

    # 发送钉钉通知
    send_dingtalk_notification(results)

if __name__ == "__main__":
    main()
