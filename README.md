# 青龙自动签到 & 状态监控脚本

基于青龙面板的自动签到与状态监控工具集合，支持多账号管理、推送通知、统一代理解析和异常处理。

> **NewAPI 签到已失效（停止维护）**：面板鉴权与接口变更导致原签到逻辑不可用，脚本 `newapi.py` 仅作存档，请勿再配置 `NEWAPI_*` 环境变量。

[![Stars](https://img.shields.io/github/stars/sheetung/ql-auto-tasks?label=Stars&color=blue&style=flat&logo=)](https://github.com/sheetung/ql-auto-tasks/stargazers)
[![Fork](https://img.shields.io/github/forks/sheetung/ql-auto-tasks?label=Fork&color=blue&style=flat&logo=)](https://github.com/sheetung/ql-auto-tasks/network)
[![Issue](https://img.shields.io/github/issues/sheetung/ql-auto-tasks?label=Issue&color=brightgreen&style=flat&logo=)](https://github.com/sheetung/ql-auto-tasks/issues)
[![visitors](https://visitor-badge.laobi.icu/badge?page_id=sheetung.ql-auto-tasks&color=blue)](https://github.com/sheetung/ql-auto-tasks)
[![license](https://img.shields.io/github/license/sheetung/ql-auto-tasks?label=license&color=green&style=flat&logo=)](https://github.com/sheetung/ql-auto-tasks/blob/master/LICENSE)

## 🌟 功能特性

1. **多账号管理**：同一任务支持多个 Cookie / 账号串行执行
2. **智能识别状态**：自动判断签到结果（成功 / 失败 / 已签到）
3. **多渠道推送**：钉钉机器人（Markdown）、Bark；复用统一环境变量
4. **统一代理解析**：`AUTO_TASK_PROXY` 一处配置，按脚本规则生效
5. **异常处理**：自动捕获网络错误、Cookie 失效等问题并通知
6. **本地状态**：监控类任务落盘对比，仅在有变动时推送
7. **日志输出**：控制台打印完整执行过程，便于青龙排查

## 📋 脚本一览

| 脚本 | 任务 | 默认 cron | 状态 |
|------|------|-----------|------|
| [`ablesci.py`](#1-科研通签到) | 科研通签到 | `0 0 * * *` | 可用 |
| [`qingw_check.py`](#2-青蛙-pt-站签到) | 青蛙 PT 站签到 | `0 10 * * *` | 可用 |
| [`ptlover_check.py`](#3-爱猫-ptlover-站签到) | 爱猫 PT 站签到 | `0 9 * * *` | 可用 |
| [`wiley_monitor.py`](#4-wiley-论文状态监控) | Wiley 论文投稿状态监控 | `35 * * * *` | 可用（需代理 + Cookie） |
| [`huawei_phone_monitor.py`](#5-华为官网新机监控) | 华为官网新机监控 | `*/30 * * * *` | 可用（国内直连） |
| [`sub2api_report.py`](#6-sub2api-日报) | sub2api 用量日报 | `0 22 * * *` | 可用（`SUB2API_ACCOUNTS`） |
| [`newapi.py`](#7-newapi已失效) | NewAPI 站点签到 | — | **已失效** |

> 代理解析已内联到各脚本，仓库中**没有**需要被青龙调度的公共库文件。

## 🚀 部署

在青龙面板「订阅管理」中添加：

| 项 | 值 |
|----|-----|
| 链接 | `https://github.com/sheetung/ql-auto-tasks.git`（旧地址 `sheetung/autoCheckin` 已迁移） |
| 分支 | `master` |
| 文件后缀 | `py` |

定时规则见各脚本文件头的 `cron:`，或下表「默认 cron」。

## ⚙️ 统一配置（所有脚本共用）

### 推送

在青龙「环境变量」或「配置文件」中设置（不配则跳过对应渠道）：

```bash
export BARK_PUSH="your_bark_key"          # Bark，也可是完整 URL
export BARK_SOUND=""                       # 可选
export DD_BOT_TOKEN="your_dingtalk_token"  # 钉钉机器人 token
export DD_BOT_SECRET="your_dingtalk_secret"
```

> 钉钉机器人安全设置请选择「自定义关键词」，添加 `autoTask`。
>
> 若日志出现 `errcode:310000 关键词不匹配`，多半是**青龙面板自带的「开始执行/结束」通知**（不含 `autoTask`）被拦了，不是本仓库脚本的业务推送。处理方式任选其一：
> 1. 青龙「系统设置 → 通知」把消息标题/内容模板加上 `autoTask`
> 2. 钉钉机器人安全设置改用「加签」，不要只靠关键词
> 3. 关闭该定时任务的青龙通知，只保留脚本自己在**有变动时**的推送（业务通知标题均已含 `【autoTask】`）

### 代理

优先级：**脚本专属变量 > `AUTO_TASK_PROXY` > 系统 `https_proxy`**。

```bash
# 推荐：需要科学上网的任务共用
export AUTO_TASK_PROXY="http://127.0.0.1:7890"
```

| 脚本 | 是否走代理 |
|------|------------|
| Wiley | 是（`WILEY_PROXY` → `AUTO_TASK_PROXY` → 系统代理） |
| 华为新机 | 默认直连；仅显式设置 `HUAWEI_PROXY` 时走代理 |
| 科研通 / PT 站 | 直连 |

---

## 脚本详情

### 1. 科研通签到

| 项 | 值 |
|----|-----|
| 文件 | `ablesci.py` |
| cron | `0 0 * * *`（每天 0 点） |
| 代理 | 直连 |

访问 [ablesci.com](https://www.ablesci.com/) 完成每日签到，支持多账号。

**环境变量**

```bash
# 多个 Cookie 用 & 分隔
export ABLESCI_COOKIES="cookie1&cookie2"
```

Cookie 获取：登录后 F12 → Network → 复制请求头中的 Cookie。

**运行示例**

```text
正在签到第 1 个账号...
正在使用 Cookie 签到: abcdefghijklmnopqr...
签到结果: {'status': 'error', 'message': '签到失败，您今天已于 [07:00:01] 签到'}
第 1 个账号签到完成

签到结果汇总：
{'status': 'error', 'message': '签到失败，您今天已于 [07:00:01] 签到'}
✅ bark推送成功
✅ 钉钉推送成功
```

---

### 2. 青蛙 PT 站签到

| 项 | 值 |
|----|-----|
| 文件 | `qingw_check.py` |
| cron | `0 10 * * *`（每天 10 点） |
| 代理 | 直连 |

访问青蛙 PT 站完成签到，解析签到天数、排名、蝌蚪数等。启动后有 0–10 分钟随机延时。

**环境变量**

```bash
# 多个 Cookie 用 & 分隔
export QINGWA_COOKIES="cookie1&cookie2"
```

**运行示例**

```text
随机延时 123.45 秒后开始签到...

➡️ 正在签到账号 1...
✅ 账号 1（username）签到成功！
   签到天数: 128天 (连续 15天)
   每日排名: 32/1200
   本次获得蝌蚪: 55个
   总蝌蚪数量: 2,058.0个
```

---

### 3. 爱猫（PTlover）站签到

| 项 | 值 |
|----|-----|
| 文件 | `ptlover_check.py` |
| cron | `0 9 * * *`（每天 9 点） |
| 代理 | 直连 |

访问爱猫 PT 站完成签到，解析签到天数、喵饼等。启动后有 0–10 分钟随机延时。

**环境变量**

```bash
# 多个 Cookie 用 & 分隔
export PTLOVER_COOKIES="cookie1&cookie2"
```

**运行示例**

```text
随机延时 88.20 秒后开始签到...

➡️ 正在签到账号 1...
✅ 账号 1（username）签到成功！
   签到天数: 200天 (连续 30天)
   本次获得喵饼: 40个
   总喵饼数量: 12,345.0个
```

---

### 4. Wiley 论文状态监控

| 项 | 值 |
|----|-----|
| 文件 | `wiley_monitor.py` |
| cron | `35 * * * *`（每小时 35 分） |
| 代理 | 需要（走 `AUTO_TASK_PROXY` 或 `WILEY_PROXY`） |

轮询 [authors.wiley.com/dashboard](https://authors.wiley.com/dashboard) 的投稿卡片，检测状态变更、新通知、新投稿并推送。

**环境变量**

```bash
# 多个账号用 & 分隔（一般只需一个）
export WILEY_COOKIES="your_wiley_cookie_here"

# 代理（与统一配置二选一即可）
export AUTO_TASK_PROXY="http://127.0.0.1:7890"
# 或
export WILEY_PROXY="http://127.0.0.1:7890"
```

Cookie 获取：登录 dashboard 后 F12 → Network → 刷新 → 任选请求 → 复制 Request Headers 中的 Cookie。

若日志出现 HTTP 401/403、non-JSON 或跳转 `/dashboard/error`，通常是 Cookie 过期或代理不可达。

Cookie 失效时会**立刻**通过 Bark/钉钉推送提醒，并附更新步骤；同一账号 **6 小时内不重复提醒**。Cookie 恢复后自动继续监控。

**运行示例**

```text
正在检查第 1 个账号...
获取到 3 篇投稿

检测到 1 个变动:
  - 状态变更: Some Paper Title [Under Review -> In Revision]
第 1 个账号检查完成

检查结果汇总：
账号1: 获取 3 篇投稿, 1 个变动
  🔍 [Under Review] MS12345: Paper A
  📝 [In Revision] MS67890: Paper B
  📤 [Submitted] MS11111: Paper C
✅ Bark推送成功
✅ 钉钉推送成功
```

状态文件：`wiley_state_0.json`（按账号序号区分）。

---

### 5. 华为官网新机监控

| 项 | 值 |
|----|-----|
| 文件 | `huawei_phone_monitor.py` |
| cron | `*/30 * * * *`（每半小时） |
| 代理 | 默认直连，不走 `AUTO_TASK_PROXY` |

无需登录。三层信号（由早到晚）：

1. **发布会/活动页** — sitemap 中 `/cn/press/events/`
2. **热门产品位** — 手机首页服务端直出链接
3. **产品页上架** — sitemap 中 `/cn/phones/<slug>/`

任一层有新增即推送；无变动只刷新本地状态。

**环境变量**

```bash
# 一般不用配
# 仅在必须走代理时：
export HUAWEI_PROXY="http://127.0.0.1:7890"
```

**运行示例**

```text
================================================
华为官网新机监控  2026-09-10 22:49:12
================================================
🔥 热门产品位 2 款: mate-xt-2-ultimate-design, pura-x-view
✅ 产品页 47 款 | 发布会候选 22 场
对比: 手机 47→47 | 发布会 22→22
✅ 今日无新增信号
💾 状态已保存: 手机 47 / 发布会 22
```

首次运行会打印完整机型/发布会列表并建立基线。状态文件：`huawei_phones_state.json`。

---

### 6. sub2api 日报

| 项 | 值 |
|----|-----|
| 文件 | `sub2api_report.py` |
| cron | `0 22 * * *`（每天 22:00） |
| 代理 | 默认直连；可设 `SUB2API_PROXY` / `AUTO_TASK_PROXY` |

调用 sub2api 的 `/api/v1/user/profile`、`/api/v1/usage/stats`、`/api/v1/usage`，汇总余额与当日用量后推送。

**环境变量**

```bash
# url@JWT，多个用 & 分隔
export SUB2API_ACCOUNTS="http://127.0.0.1:18080@eyJhbGciOi..."
# 多站点：http://host1:port@token1&http://host2:port@token2
```

使用**控制台 JWT**（约 1 天过期，需定期更换）。  
说明：`sk-` API Key 的 `/v1/usage` **只统计该 Key 自身额度**，看不到账号级用量，故不用作日报。

请求头：`Authorization: Bearer <token>`

**安全提示（务必遵守）**

1. **JWT / API Key 都是密钥**，只放青龙环境变量，**不要写进仓库或聊天**
2. 密钥泄露可被用来调用模型烧余额；请定期轮换
3. **务必设置额度限制**（配额 / 余额告警 / 限额），避免泄露后被刷爆
4. **仅用作 API 请求**，不要把密钥用于其他场景或共用给不可信服务
5. **建议 sub2api 仅部署在内网**；若必须公网访问，请加 HTTPS、强密码与 IP 白名单
6. 青龙与 sub2api 同内网时，优先直连，避免经过第三方代理

**运行示例（JWT）**

```text
http://127.0.0.1:18080
账号｜user@example.com [active]
余额｜9931.38
今日｜431次 · 65.64M · 花费 67.62
延迟｜均 25.3s
模型｜gpt-6-astra×250  codex-auto-review×181
```

推送标题：`【autoTask】sub2api日报`。钉钉用 text 消息保换行。

---

### 7. NewAPI（已失效）

| 项 | 值 |
|----|-----|
| 文件 | `newapi.py` |
| 状态 | **停止维护，请勿配置** |

> 面板接口/鉴权变更导致签到不可用。请删除 `NEWAPI_ACCOUNTS` / `NEWAPI_ACCOUNTS_JSON` / `NEWAPI_PROXY`，停用定时任务。文件仅作历史存档。

---

## ⚠️ 注意事项

1. 钉钉推送需正确配置机器人权限（自定义关键词 `autoTask`，以及 `DD_BOT_SECRET`）
2. **NewAPI 任务已失效**，请勿再配置 `NEWAPI_*` 或启用对应定时任务
3. Wiley 依赖可达代理；Cookie 失效时重新登录官网抓取
4. PT 站签到带随机延时，属正常现象
5. 本工具仅用于学习交流，禁止用于商业用途

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
