# -*- coding: utf-8 -*-
"""
new Env('科研通签到');
name: 科研通签到
cron: 0 0 * * *
"""
import os
import requests
import time
import hmac
import hashlib
import base64
import urllib.parse

# 添加bark推送
bark_push = "https://api.day.app/{key}" #(自建推送的自行替换整段url，非自建只需替换key即可)
bark_group = "AbleSci"
bark_icon = "https://staticres.ablesci.com/apple-touch-icon.png"
bark_sound = os.environ.get("BARK_SOUND", "")

# 添加钉钉推送
dingtalk_token = os.environ.get("DD_BOT_TOKEN", "")
dingtalk_secret = os.environ.get("DD_BOT_SECRET", "")

class AbleSci:
    name = "科研通签到"

    def __init__(self, cookie):
        self.cookie = cookie

    def sign(self):
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": self.cookie,
            "DNT": "1",
            "Referer": "https://www.ablesci.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        }
        url = "https://www.ablesci.com/user/sign"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            return {"status": "success", "message": "签到成功", "data": result}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"签到失败: {str(e)}"}

    def main(self):
        print(f"正在使用 Cookie 签到: {self.cookie[:20]}...")
        result = self.sign()
        print(f"签到结果: {result}")
        return result

def send_bark_notification(results):
    if not bark_push:
        print("未配置Bark推送，跳过通知")
        return

    title = "【autoTask】科研通签到"
    body_lines = []

    for idx, result in enumerate(results, 1):
        if result.get('status') == 'success':
            msg = result.get('data', {}).get('msg', '签到成功（无详细信息）')
            body_lines.append(f"账号{idx}: {msg}")
        else:
            error = result.get('message', '未知错误')
            body_lines.append(f"账号{idx}: ❌签到失败 - {error}")

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

    title = "【autoTask】科研通签到"
    text_lines = []
    text_lines.append(f"# {title}")
    for idx, result in enumerate(results, 1):
        if result.get('status') == 'success':
            msg = result.get('data', {}).get('msg', '签到成功（无详细信息）')
            text_lines.append(f"账号{idx}: {msg}\n")
        else:
            error = result.get('message', '未知错误')
            text_lines.append(f"账号{idx}: ❌签到失败 - {error}\n")

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
        print(f"钉钉响应：{resp.text}")  # 新增打印
        resp.raise_for_status()
        print("✅ 钉钉推送成功")
    except requests.exceptions.HTTPError as e:
        print(f"❌ 钉钉推送失败: {e}")
        print(f"错误详情: {resp.text}")  # 新增打印
    except Exception as e:
        print(f"❌ 钉钉推送失败: {str(e)}")

def main():
    cookies = os.getenv("ABLESCI_COOKIES")
    if not cookies:
        print("未找到环境变量 ABLESCI_COOKIES，请检查配置")
        return

    cookie_list = cookies.split("&")
    results = []
    for i, cookie in enumerate(cookie_list):
        print(f"正在签到第 {i + 1} 个账号...")
        try:
            result = AbleSci(cookie).main()
            results.append(result)
        except Exception as e:
            results.append({"status": "error", "message": f"第 {i + 1} 个账号签到失败: {str(e)}"})
        print(f"第 {i + 1} 个账号签到完成\n")

    print("\n签到结果汇总：")
    for result in results:
        print(result)

    # 发送Bark通知
    send_bark_notification(results)

    # 发送钉钉通知
    send_dingtalk_notification(results)

if __name__ == "__main__":
    main()
