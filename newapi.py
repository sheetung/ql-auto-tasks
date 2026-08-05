# -*- coding: utf-8 -*-
"""
new Env('NewAPI签到');
name: NewAPI签到
cron: 0 0 * * *
"""
import os
import requests
import time
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime

# 添加bark推送
bark_push = "https://api.day.app/{key}" #(自建推送的自行替换整段url，非自建只需替换key即可)
bark_group = "NewAPI"
bark_icon = "https://staticres.ablesci.com/apple-touch-icon.png"
bark_sound = os.environ.get("BARK_SOUND", "")

# 添加钉钉推送
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

class NewAPI:
    name = "NewAPI签到"

    def __init__(self, url, cookie, user_id="2"):
        self.url = url.rstrip('/')
        self.cookie = cookie
        
        # 从cookie中提取用户ID（如果存在）
        if "user_id=" in cookie:
            self.user_id = cookie.split("user_id=")[1].split("&")[0]
        elif "userid=" in cookie:
            self.user_id = cookie.split("userid=")[1].split("&")[0]
        elif "uid=" in cookie:
            self.user_id = cookie.split("uid=")[1].split("&")[0]
        else:
            self.user_id = user_id

    def sign(self):
        # 签到URL，根据NewAPI站点的实际签到接口调整
        # 从测试结果看，正确的接口路径是 /api/user/checkin
        sign_url = f"{self.url}/api/user/checkin"
        
        # 基础头部
        base_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "DNT": "1",
            "Referer": f"{self.url}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        # 读取代理环境变量
        proxies = {}
        newapi_proxy = os.environ.get("NEWAPI_PROXY") or os.environ.get("newapi_proxy")
        
        if newapi_proxy:
            proxies["http"] = newapi_proxy
            proxies["https"] = newapi_proxy
        
        if proxies:
            print(f"使用代理: {proxies}")
        
        # 尝试不同的认证方式
        auth_attempts = []
        
        # 尝试: 使用session cookie认证
        if "session=" in self.cookie:
            auth_attempts.append({
                "name": "session cookie",
                "headers": dict(base_headers, **{
                    "Cookie": self.cookie,
                    "New-Api-User": self.user_id
                })
            })
        
        # 尝试: 默认使用cookie认证
        auth_attempts.append({
            "name": "default cookie",
            "headers": dict(base_headers, **{
                "Cookie": self.cookie
            })
        })
        
        # 尝试每种认证方式
        for attempt in auth_attempts:
            print(f"尝试认证方式: {attempt['name']}")
            try:
                # 尝试使用POST请求进行签到
                response = requests.post(sign_url, headers=attempt['headers'], proxies=proxies)
                
                # 处理响应
                if response.status_code == 200:
                    # 检查是否是Cloudflare验证页面
                    if '<title>Just a moment...</title>' in response.text or 'cloudflare' in response.text.lower():
                        print(f"认证方式 {attempt['name']} 遇到Cloudflare验证")
                        return {"status": "error", "message": "签到失败: 遇到Cloudflare人机验证，请手动访问站点完成验证后再尝试"}
                    
                    try:
                        result = response.json()
                        
                        # 无论是签到成功还是今日已签到，都尽量继续拉取详情统计
                        detail_response = requests.get(sign_url, headers=attempt['headers'], proxies=proxies)
                        if detail_response.status_code == 200:
                            # 检查详细信息是否是Cloudflare验证页面
                            if '<title>Just a moment...</title>' in detail_response.text or 'cloudflare' in detail_response.text.lower():
                                print("获取详细信息时遇到Cloudflare验证")
                            else:
                                try:
                                    detail_result = detail_response.json()
                                    result['detail'] = detail_result
                                except:
                                    pass

                        return {"status": "success", "message": "签到成功", "data": result}
                    except ValueError:
                        # 响应不是JSON格式，可能是Cloudflare验证页面
                        if '<title>Just a moment...</title>' in response.text or 'cloudflare' in response.text.lower():
                            print(f"认证方式 {attempt['name']} 遇到Cloudflare验证")
                            return {"status": "error", "message": "签到失败: 遇到Cloudflare人机验证，请手动访问站点完成验证后再尝试"}
                        else:
                            print(f"认证方式 {attempt['name']} 响应不是JSON格式: {response.text[:100]}...")
                            return {"status": "error", "message": "签到失败: 响应格式错误"}
                elif response.status_code == 403:
                    # 403错误可能是Cloudflare验证
                    if '<title>Just a moment...</title>' in response.text or 'cloudflare' in response.text.lower():
                        print(f"认证方式 {attempt['name']} 遇到Cloudflare验证")
                        return {"status": "error", "message": "签到失败: 遇到Cloudflare人机验证，请手动访问站点完成验证后再尝试"}
                    else:
                        print(f"认证方式 {attempt['name']} 失败: {response.status_code}")
                else:
                    print(f"认证方式 {attempt['name']} 失败: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"认证方式 {attempt['name']} 异常: {str(e)}")
        
        # 所有认证方式都失败
        return {"status": "error", "message": "签到失败: 所有认证方式都失败，可能需要有效的access token"}

    def main(self):
        print(f"正在签到站点: {self.url}")
        print(f"使用 Cookie: {self.cookie[:20]}...")
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
            details['today_quota'] = current_record.get('quota_awarded') or 0
        else:
            details['total_checkins'] = stats.get('total_checkins', 0)

        if stats.get('checkin_today'):
            details['is_already_checked'] = True

    return details


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
    # 读取环境变量 NEWAPI_ACCOUNTS，格式为 url@userid@cookie&url@userid@cookie
    accounts = os.getenv("NEWAPI_ACCOUNTS")
    if not accounts:
        print("未找到环境变量 NEWAPI_ACCOUNTS，请检查配置")
        return

    # 解析账号列表
    # 注意：需要正确处理cookie中包含&的情况
    account_list = []
    current_account = ""
    at_count = 0
    
    for char in accounts:
        if char == "@":
            at_count += 1
            current_account += char
        elif char == "&" and at_count >= 2:
            account_list.append(current_account)
            current_account = ""
            at_count = 0
        else:
            current_account += char
    
    if current_account:
        account_list.append(current_account)
    
    results = []
    
    for i, account in enumerate(account_list):
        print(f"正在签到第 {i + 1} 个站点...")
        try:
            # 解析 url@userid@cookie 格式
            parts = account.split("@")
            if len(parts) == 3:
                url, user_id, cookie = parts
            else:
                # 兼容旧格式 url@cookie
                url, cookie = parts
                user_id = "2"  # 默认为用户ID 2
            
            # 使用正确的路径进行签到
            result = NewAPI(url, cookie, user_id).main()
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
