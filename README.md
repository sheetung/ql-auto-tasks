# 青龙自动签到 & 状态监控脚本

基于青龙面板的自动签到与状态监控工具，支持科研通、NewAPI签到、Wiley论文投稿状态监控和华为官网新机监控，支持多账号/多站点管理、推送通知和异常处理。

![image](https://img.shields.io/github/stars/sheetung/autoCheckin) | ![image](https://img.shields.io/github/forks/sheetung/autoCheckin) | ![image](https://img.shields.io/github/issues/sheetung/autoCheckin)

## 🌟 功能特性

1. **多账号/多站点管理**：
   - 科研通：支持多个账号同时签到
   - NewAPI：支持多个站点同时签到
   - Wiley：支持多账号论文投稿状态监控（检测状态变更、新通知等）
2. **华为新机监控**：定时抓取华为中国站 sitemap，对比本地基线，发现新发布/下架手机型号时推送通知
3. **智能识别状态**：自动判断签到结果（成功 / 失败 / 已签到）
4. **详细签到信息**：
   - 科研通：显示签到状态
   - NewAPI：显示签到状态、累计天数、获得金额和历史记录
5. **多推送通知**：
   - 钉钉机器人消息提醒（支持 Markdown 格式）
   - Bark 消息推送（iOS 专属，未测试）
6. **异常处理机制**：自动捕获网络错误、Cookie 失效等问题
7. **日志记录**：控制台输出详细的签到过程和结果

## 🚀 使用方法

### 1. 订阅配置

在青龙面板「订阅管理」中添加：

- **名称**：签到脚本
- **链接**：`https://github.com/sheetung/autoCheckin.git`
- **分支**：`master`
- **定时规则**：根据需求设置（例如 `0 0 * * *` 每天凌晨执行）
- **文件后缀**：`py`

### 2. 环境变量配置

#### 科研通
在青龙面板「环境变量」中设置：

```bash
# 多个Cookie用&分隔
export ABLESCI_COOKIES="cookie1&cookie2&cookie3"
```

#### NewAPI
在青龙面板「环境变量」中设置：

```bash
# 推荐使用 JSON，pat 是“个人设置”中的面板访问令牌（User.AccessToken）
export NEWAPI_ACCOUNTS_JSON='[{"url":"https://sample.com","pat":"your_panel_pat"}]'

# 简写格式；多个站点用 & 分隔，每项为 url@PAT
export NEWAPI_ACCOUNTS="https://sample.com@your_panel_pat&https://another.example.com@another_panel_pat"
```

> 必须使用面板 PAT，不是浏览器 Network 中的短期 Bearer JWT，也不是“令牌管理”中用于调用模型的 `sk-` API Key。新版浏览器 Access Token 通常仅有效 15 分钟，无法用于定时任务；旧 `session` Cookie 和 `New-Api-User` 已不再支持。

#### Wiley论文状态监控
在青龙面板「环境变量」中设置：

```bash
# 多个账号用&分隔（一般只需一个）
export WILEY_COOKIES="your_wiley_cookie_here"
```

Cookie 获取方式：登录 https://authors.wiley.com/dashboard 后，F12 打开开发者工具 → Network → 刷新页面 → 点击任意请求 → 复制 Request Headers 中的 Cookie 值。

#### PT 站点签到

已合并爱猫（PTlover）和青蛙两个 PT 站点签到任务，对应脚本为 `ptlover_check.py` 和 `qingw_check.py`。

```bash
# 爱猫站点，多账号 Cookie 使用 & 分隔
export PTLOVER_COOKIES="cookie1&cookie2"

# 青蛙站点，多账号 Cookie 使用 & 分隔
export QINGWA_COOKIES="cookie1&cookie2"
```

两个任务会复用工程中的 `BARK_PUSH`、`BARK_SOUND`、`DD_BOT_TOKEN` 和 `DD_BOT_SECRET` 通知配置。钉钉机器人安全设置请选择“自定义关键词”，添加 `autoTask`。

#### 华为官网新机监控

脚本：`huawei_phone_monitor.py`，默认 cron `*/30 * * * *`（每半小时）。

无需 Cookie / 账号。**三层信号**（由早到晚）：

1. **发布会/活动页** — 从 sitemap 解析 `/cn/press/events/`，发布会官宣后活动页会较早进 sitemap
2. **热门产品位** — 手机首页服务端直出的热门链接，旗舰预热时常先出现
3. **产品页上架** — sitemap 中 `/cn/phones/<slug>/`，确认产品详情页已挂

任一层有新增即推送；无变动只刷新本地状态。

可选环境变量：

```bash
# 可选：代理
export HUAWEI_PROXY="http://127.0.0.1:7890"
```

推送复用 `BARK_PUSH`、`BARK_SOUND`、`DD_BOT_TOKEN`、`DD_BOT_SECRET`。

> 防爬情况：官网列表页是 JS 动态渲染，但 sitemap 与首页热门产品区为服务端输出，普通 UA + requests 即可稳定抓取，无需登录/Cookie，也未见验证码拦截。脚本内置重试与 UA 伪装；默认每半小时检查一次，无变动时只写本地状态、不推送。


### 3. 代理配置（可选）

在青龙面板「配置文件」中设置：

```bash
# NewAPI 代理配置（可选）
export NEWAPI_PROXY="http://127.0.0.1:7890"

# Wiley 代理配置（可选，不设置则使用系统代理）
export WILEY_PROXY="http://127.0.0.1:7890"
```

### 4. 推送配置（可选）

在青龙面板「配置文件」中设置：

```bash
# 钉钉推送配置（可选）
export DD_BOT_TOKEN="your_dingtalk_token"
export DD_BOT_SECRET="your_dingtalk_secret"

# 钉钉机器人安全设置：选择“自定义关键词”，添加 autoTask

# Bark推送配置（可选，未测试）
export BARK_PUSH="your_bark_key"
```

## 📦 部署说明

1. 确保青龙面板已安装 Python 环境
2. 通过 Git 或手动上传方式部署脚本
3. 首次运行前检查环境变量是否正确配置

## 📝 运行示例

### 科研通

```bash
正在签到第 1 个账号...
正在使用 Cookie 签到: abcdefghijklmnopqr...
签到结果: {'status': 'error', 'message': '签到失败，您今天已于 [07:00:01] 签到'}
第 1 个账号签到完成

签到结果汇总：
{'status': 'error', 'message': '签到失败，您今天已于 [07:00:01] 签到'}
✅ bark推送成功
✅ 钉钉推送成功
```

### NewAPI

```bash
正在签到第 1 个站点...
正在签到站点: https://sg.uiuiapi.com
使用认证方式: 面板 PAT
尝试认证方式: 面板 PAT
签到结果: {'status': 'success', 'message': '签到成功', 'data': {'message': '今日已签到', 'success': False}}
第 1 个站点签到完成

签到结果汇总：
站点: https://sg.uiuiapi.com/
结果: {'status': 'success', 'message': '签到成功', 'data': {'message': '今日已签到', 'success': False}}

❌ Bark推送失败: 400 Client Error: Bad Request for url: https://api.day.app/%7Bkey%7D
未配置钉钉推送，跳过通知
```

### 华为新机监控

```bash
================================================
华为官网新机监控  2026-09-10 22:40:31
================================================
✅ 从 sitemap.xml 解析到 47 款手机
对比基线: 旧 47 款 → 新 47 款
✅ 今日无新增/下架手机型号
💾 状态已保存: .../huawei_phones_state.json（共 47 款）
```

首次运行会打印完整机型列表并建立基线；后续仅有变动时才推送。

## ⚠️ 注意事项

1. 钉钉推送功能需要正确配置机器人权限，例如关键词和`DD_BOT_SECRET`
2. NewAPI 仅使用面板 PAT 认证；脚本不会输出 PAT，也不会使用旧 Cookie、短期浏览器 JWT 或 `New-Api-User`
3. 本工具仅用于学习交流，禁止用于商业用途

## 📜 声明

```plaintext
本项目所有代码仅用于学习和研究目的，严禁用于商业用途。
用户需遵守相关网站的用户协议及相关法律法规。
下载后请在24小时内删除，否则一切法律后果自负。
```

## 📢 反馈与贡献

- 提交问题：[GitHub Issues](https://github.com/sheetung/autoCheckin/issues)
- 代码贡献：[Fork & Pull Request](https://github.com/sheetung/autoCheckin/pulls)

> 开源协议：MIT License
