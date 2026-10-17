# B站每日任务自动化（bili-auto）

纯 Python 标准库实现，**零第三方依赖**。支持本地运行、Docker 常驻、GitHub Actions 定时。

> 仅用于自己账号的日常任务。违反平台用户协议的风险由使用者承担，
> 请勿用于批量养号，也不要外传 Cookie。

---

## 一、已验证的部分

WBI 签名算法不是猜的，是**联网跑通的**：

```
$ python run.py selftest
1. 获取 WBI key ...
   [OK] mixin_key = ea1db124af3c7062474693fa704f4ff8
2. 计算签名并请求需要签名的接口 ...
   [OK] 服务端接受签名，视频标题 = 【官方 MV】Never Gonna Give You Up - Rick Astley

selftest: [OK] WBI 签名算法正确
```

也就是说：`code=0` 说明服务端认可我们算出来的 `w_rid`。
这个是整套工具的基石，它没问题，剩下的只是「调哪几个接口」。

---

## 二、这个工具到底做什么

B站早就没有「签到」这个动作了，所谓每日任务其实是这套：

| 任务 | 经验 | 默认 | 做法 |
|---|---|---|---|
| 观看视频 | +5 | 开 | 向 `/x/click-interface/web/heartbeat` 上报几次播放进度 |
| 分享视频 | +5 | 开 | `POST /x/web-interface/share/add` |
| 点赞 | +5 | 开 | `POST /x/web-interface/archive/like` |
| 领取奖励 | +10 | 开 | `GET /x/member/web/exp/reward` |
| 直播签到 | 少量经验+辣条 | 开 | `GET api.live.bilibili.com/xlive/web-ucenter/v1/sign/DoSign` |
| 投币 | +10/币（上限 2） | **关** | `POST /x/web-interface/coin/add` |

工具会自动挑当天热门榜第一个视频，对同一个视频完成观看、点赞、分享，然后领取奖励。

### 关于投币：默认关闭

投币会**消耗你账户里的硬币**，
所以默认是关闭的 —— 白嫖模式。

不含投币时，每天大约 30 经验；想开就把 `daily.coin` 改成 `true`，
再用 `daily.coin_num` 控制投几个（1 或 2）。

只想临时投一次、不想改配置，可以单独跑：

```bash
python run.py daily --only coin
```


---

## 三、思路（为什么这么设计）

**1. 先解决签名，再谈功能。**

B站 2023 年起对大量接口加了 WBI 签名，没有它连视频详情都拿不到。
所以我把 `wbi.py` 单独成模块，并且提供 `selftest` 子命令 ——
**任何时候怀疑失效，先跑 selftest**：它成功说明签名没问题，失败就是算法变了。
这样排障时能一刀切开「是签名坏了」还是「是接口改了」。

**2. 为什么 Cookie 必须包含两个字段。**

- `SESSDATA`：登录凭证，服务器靠它认出你是谁；
- `bili_jct`：CSRF token，所有写操作（点赞/投币/分享）都要在 body 里带上它。

少了 `bili_jct`，查询类接口正常、写操作全部 `-111`（csrf 校验失败），
这个坑很多人踩。所以取 Cookie 时**两个都要**。

**3. 为什么视频要从热门榜动态取？**

写死一个 `av` 号的问题：视频可能被删、可能已经点过赞、可能自己投过币，
那样任务会静默失败。从「热门」取第一个，每天都是新的，几乎不会撞上。

**4. 为什么每个任务独立、可单独运行？**

B站 接口偶尔会单独失效（比如分享接口改版）。任务拆开之后，
`--only coin` 就能只测投币，出问题能精准定位到某一步，而不是"整体挂了"。

**5. 为什么要有 dry-run？**

第一次跑之前，先 `--dry-run` 看看它打算做哪几件事。
确认无误再真跑，避免"一上来就把币投给莫名其妙的视频"。

---

## 四、快速开始

### 第 1 步：拿到 Cookie

因为 `SESSDATA` 是 **HttpOnly**，控制台敲 `document.cookie` 拿不到，必须用下面的方法：

**方法 A：开发者工具（最直接）**
1. Chrome 打开并登录 `https://www.bilibili.com`
2. 按 `F12` → 切到 **Application / 应用** 标签
3. 左侧 **Storage → Cookies → https://www.bilibili.com**
4. 找到 `SESSDATA` 和 `bili_jct`，各复制一次 Value

**方法 B：用插件导出（更省事）**
1. 装 **Cookie-Editor** 或 **EditThisCookie**
2. 在 B站 页面点插件 → Export → 复制 JSON
3. 存成 `cookies.json`，然后：

```bash
python tools/cookie_from_json.py cookies.json --config config.json
```

它会自动挑出 B站 相关字段、拼成 Cookie 串、写进配置。

### 第 2 步：验证

```bash
python run.py init                  # 生成 config.json
# 把 cookie 填进去，或者直接用环境变量 BILI_COOKIE
python run.py check                 # 应该输出「已登录：你的昵称（Lv6...）」
```

### 第 3 步：先看再做

```bash
python run.py daily --dry-run       # 列出今天要做什么
python run.py daily                 # 真跑
python run.py daily --only coin     # 只投币
```

---

## 五、部署

### 方式 A：本机定时（最简单）

Linux `crontab`：

```cron
7 9 * * * cd /opt/bili-auto && BILI_COOKIE="..." /usr/bin/python3 run.py daily >> run.log 2>&1
```

Windows 任务计划程序：

```
程序：python
参数：D:\path\to\bili-auto\run.py daily
起始位置：D:\path\to\bili-auto
```

### 方式 B：GitHub Actions（免费、不用开电脑）

1. 把项目推到自己的**私有**仓库
2. `Settings → Secrets and variables → Actions`：
   - 添加 Secret `BILI_COOKIE`，值是完整 Cookie 串
   - 可选：`BILI_NOTIFY_TYPE`、`BILI_NOTIFY_KEY`
3. 启用 `.github/workflows/bili-daily.yml`

工作流已配好：UTC 01:07（北京时间 09:07）执行，也支持手动触发。
**注意：仓库里不需要任何配置文件**，Cookie 全走 Secrets。

### 方式 C：Docker 常驻

```bash
cd deploy
BILI_COOKIE="你的cookie" docker compose up -d --build
docker compose logs -f
```

容器内每天 09:10（上海时区）自动跑一次。

---

## 六、排错

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `-101 账号未登录` | `SESSDATA` 过期或没填 | 重新取 Cookie，有效期约 6 个月 |
| `-111 csrf 校验失败` | 缺 `bili_jct` | 把 `bili_jct` 一起填进来 |
| `-403 / -352` | 签名错误或被风控 | 先跑 `selftest`；通过则降低频率 |
| `-412 请求被拦截` | 请求太快、UA 可疑 | 调大 `min_interval`（默认 1.0 秒） |
| `-509 超出限制` | 频率过高 | 等几小时再试 |
| `34005` | 今日投币已达上限 | 正常，已按成功处理 |
| 分享总是失败 | 分享接口改版 | `daily.share_video` 设 false，不影响其他任务 |

**万能第一步：`python run.py selftest`。** 它区分「签名问题」和「接口问题」。

---

## 七、风险提醒

- **Cookie 等同于账号密码**。任何网站、脚本、"代挂服务"要你贴 Cookie，都等于把号交出去。
- GitHub Actions 仓库必须设为**私有**，否则 Secret 虽然看不到，但别人能 fork 你的工作流。
- 默认 `min_interval = 1.0` 秒，别调太低；B站 对高频请求的风控是 `-412`。
- 大会员、粉丝牌等权益相关接口本项目不涉及，避免误操作。
- 建议先用小号跑一周，确认稳定再换大号。

---

## 八、目录结构

```
bili-auto/
├── run.py                     入口
├── src/
│   ├── wbi.py                 ★ WBI 签名（含乱序表）
│   ├── client.py              HTTP：Cookie / CSRF / 重试 / 限速 / 签名自动刷新
│   ├── config.py              配置 + 环境变量
│   ├── tasks.py               ★ 每日任务实现
│   ├── notify.py              结果推送
│   └── cli.py                 命令行
├── tools/
│   └── cookie_from_json.py    插件导出的 Cookie → 配置
├── deploy/                    Docker 相关
├── .github/workflows/         GitHub Actions
└── config.example.json
```
