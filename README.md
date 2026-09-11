# 青龙自动签到 & 状态监控脚本

基于青龙面板的自动签到与状态监控工具，支持科研通签到、Wiley论文投稿状态监控和华为官网新机监控，支持多账号管理、推送通知和异常处理。

> **NewAPI 签到已失效（停止维护）**：面板鉴权与接口变更导致原签到逻辑不可用，脚本 `newapi.py` 仅作存档，请勿再配置 `NEWAPI_*` 环境变量。

![image](https://img.shields.io/github/stars/sheetung/autoCheckin) | ![image](https://img.shields.io/github/forks/sheetung/autoCheckin) | ![image](https://img.shields.io/github/issues/sheetung/autoCheckin)

## 🌟 功能特性

1. **多账号管理**：
   - 科研通：支持多个账号同时签到
   - Wiley：支持多账号论文投稿状态监控（检测状态变更、新通知等）
2. **华为新机监控**：三层信号监控官网新机（发布会活动页 / 热门产品位 / 产品页上架）
3. **智能识别状态**：自动判断签到结果（成功 / 失败 / 已签到）
4. **多推送通知**：
   - 钉钉机器人消息提醒（支持 Markdown 格式）
   - Bark 消息推送（iOS 专属，未测试）
5. **统一代理解析**：`AUTO_TASK_PROXY` 一处配置；华为默认直连
6. **异常处理机制**：自动捕获网络错误、Cookie 失效等问题
7. **日志记录**：控制台输出详细的签到过程和结果

## 🚀 使用方法

### 1. 订阅配置

在青龙面板「订阅管理」中添加：

- **名称**：签到脚本
- **链接**：`https://github.com/sheetung/ql-auto-tasks.git`（旧地址 `sheetung/autoCheckin` 已迁移）
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

#### NewAPI（已失效，勿配置）

> ⚠️ **该任务已失效**：面板接口/鉴权变更导致签到不可用，**不再维护**。
> 请删除青龙中的 `NEWAPI_ACCOUNTS` / `NEWAPI_ACCOUNTS_JSON` / `NEWAPI_PROXY`，并停用 `newapi.py` 定时任务。
> 脚本文件保留仅作历史存档，下文配置不再适用。

#### Wiley论文状态监控
在青龙面板「环境变量」中设置：

```bash
# 多个账号用&分隔（一般只需一个）
export WILEY_COOKIES="your_wiley_cookie_here"
```

Cookie 获取方式：登录 https://authors.wiley.com/dashboard 后，F12 打开开发者工具 → Network → 刷新页面 → 点击任意请求 → 复制 Request Headers 中的 Cookie 值。

若监控报 Cookie 失效或跳转到 error 页，优先检查代理是否可达（见下文「代理配置」）。

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
# 一般无需配置；华为官网国内直连，不走 AUTO_TASK_PROXY
# 仅在必须走代理时：
export HUAWEI_PROXY="http://127.0.0.1:7890"
```

推送复用 `BARK_PUSH`、`BARK_SOUND`、`DD_BOT_TOKEN`、`DD_BOT_SECRET`。

> 防爬情况：官网列表页是 JS 动态渲染，但 sitemap 与首页热门产品区为服务端输出，普通 UA + requests 即可稳定抓取，无需登录/Cookie，也未见验证码拦截。

### 3. 代理配置（可选）

统一代理参数，一次配置多处生效。优先级：**脚本专属 > `AUTO_TASK_PROXY` > 系统 `https_proxy`**。

在青龙面板「配置文件」中设置：

```bash
# 推荐：统一代理（Wiley 等需要科学上网的任务共用）
export AUTO_TASK_PROXY="http://127.0.0.1:7890"

# 可选：脚本级覆盖（一般不用）
export WILEY_PROXY="http://127.0.0.1:7890"

# 华为官网国内直连，默认不走 AUTO_TASK_PROXY
# 仅在必须走代理时才设置：
# export HUAWEI_PROXY="http://127.0.0.1:7890"
```

| 脚本 | 读取顺序 |
|------|----------|
| Wiley | 专属 `WILEY_PROXY` → `AUTO_TASK_PROXY` → 系统 `https_proxy` |
| 华为新机监控 | 仅 `HUAWEI_PROXY`（默认直连，不受统一代理影响） |
| 科研通 / PT 站 | 默认直连，不走代理 |

公共解析逻辑在 `proxy_util.py`。

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

### 华为新机监控

```bash
================================================
华为官网新机监控  2026-09-10 22:49:12
================================================
🔥 热门产品位 2 款: mate-xt-2-ultimate-design, pura-x-view
✅ 产品页 47 款 | 发布会候选 22 场
对比: 手机 47→47 | 发布会 22→22
✅ 今日无新增信号
💾 状态已保存: 手机 47 / 发布会 22
```

首次运行会打印完整机型列表并建立基线；后续仅有变动时才推送。

## ⚠️ 注意事项

1. 钉钉推送功能需要正确配置机器人权限，例如关键词和 `DD_BOT_SECRET`
2. **NewAPI 任务已失效**，请勿再配置 `NEWAPI_*` 环境变量或启用对应定时任务
3. Wiley 监控依赖可达的代理；Cookie 失效时请重新登录官网抓取 Cookie
4. 本工具仅用于学习交流，禁止用于商业用途

## 📜 声明

```plaintext
本项目所有代码仅用于学习和研究目的，严禁用于商业用途。
用户需遵守相关网站的用户协议及相关法律法规。
下载后请在24小时内删除，否则一切法律后果自负。
```

## 📢 反馈与贡献

- 提交问题：[GitHub Issues](https://github.com/sheetung/ql-auto-tasks/issues)
- 代码贡献：[Fork & Pull Request](https://github.com/sheetung/ql-auto-tasks/pulls)

> 开源协议：MIT License
