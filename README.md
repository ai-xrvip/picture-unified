# 统一爬取框架（picture-unified）

三个独立项目（`4khd` / `eh` / `xrw`）合并为一个仓库、一套核心代码、一套 GitHub Actions 调度。
公共流水线只写一遍：**抓列表 → 抓图集直链 → 下载 → 上传/直链 → Telegraph 页面 → 封面发 TG → 记录 seen**。

## 数据源

| 源 | 原项目 | 网站 | 图片策略 | 发送目标 | AI |
|---|---|---|---|---|---|
| `eh` | E:\codex\picture\eh | e-hentai.org cosplay (f_cats=959) | pixhost 上传 | 频道 @cos4khd | Agnes 中文标题+标签 |
| `meirentu` | 原 E:\codex\picture\xrw | meirentu.cc（页内从底往上；标题自动清洗） | pixhost 上传 | 双频道（非VIP 前20张 / VIP 全图） | 无 |
| `4khd` | E:\codex\picture\4khd | 4khd.com（首页+cosplay） | Telegraph 直嵌原图 | 频道 + 可选群组 | DeepSeek 标签 / 本地库 |

## 目录结构

```
picture-unified/
├── run.py                  # 统一入口
├── channels.json           # 频道配置（${ENV} 引用）
├── migrate_state.py        # 一次性迁移旧项目状态
├── core/                   # 公共框架
│   ├── config.py           # env / 频道配置
│   ├── state.py            # seen 状态（按源隔离 + 文件锁）
│   ├── network.py          # 重试 GET / 会话
│   ├── images.py           # 下载/校验/裁剪/封面
│   ├── uploader.py         # pixhost 上传
│   ├── telegraph.py        # Telegraph 页面
│   ├── telegram.py         # TG 发送
│   └── ai.py               # OpenAI 兼容 AI 调用
├── sources/                # 数据源插件
│   ├── eh.py / meirentu.py / k4hd.py
├── state/                  # git 跟踪的状态（eh_seen.json 等）
└── .github/workflows/      # eh.yml / meirentu.yml / k4hd.yml
```

## 本地运行

```powershell
pip install -r requirements.txt
$env:PYTHONUTF8="1"

# 只抓取分析，不下载不发送不改状态
python run.py meirentu --dry-run --limit 2
python run.py eh      --dry-run --limit 1
python run.py 4khd    --dry-run --limit 1

# 正式运行（需配置环境变量，见下）
python run.py eh
python run.py meirentu
python run.py 4khd
```

其它参数：`--limit N`（本次上限）、`--start-page N`（meirentu 起始页）、`--state-dir DIR`（默认 `state/`）、`--list`。

## 环境变量

| 源 | 变量 | 必填 | 说明 |
|---|---|---|---|
| 通用 | `TELEGRAPH_TOKEN` | 是（除 dry-run） | Telegraph 账号 token，三个源可共用 |
| eh | `BOT_TOKEN` | 是 | Telegram bot token |
| eh | `MAIN_CHANNEL_ID` | 是 | 频道（如 `@cos4khd`） |
| eh | `EH_MEMBER_ID` / `EH_PASS_HASH` | 是 | e-hentai 会员 cookie（ipb_*） |
| eh | `EH_CF_CLEARANCE` | 否 | cf_clearance cookie，过期需从浏览器复制 |
| eh | `AGNES_API_KEY` / `AGNES_MODEL` / `AGNES_BASE_URL` | 否 | Agnes AI（默认 agnes-2.0-flash） |
| meirentu | `TG_TOKEN` | 是 | bot token |
| meirentu | `TG_CHAT_ID_A` / `TG_CHAT_ID_B` | 是 | 非VIP / VIP 频道 ID |
| meirentu | `VIP_LINK` | 否 | 非VIP 频道会员引导链接（默认 xiuren88bot） |
| 4khd | `TG_TOKEN` | 是 | bot token |
| 4khd | `TG_CHAT_ID_4KHD` | 是 | 主频道 ID |
| 4khd | `TG_GROUP_ID` | 否 | 可选群组（不配则不发） |
| 4khd | `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | 否 | DeepSeek 标签（默认 deepseek-chat） |

频道配置默认在 `channels.json`（`${VAR}` 会从环境变量解析）；也可以给某个源单独覆盖：
`CHANNELS_EH='[{"chat_id":"@xxx"}]'`、`CHANNELS_MEIRENTU='[...]'`、`CHANNELS_4KHD='[...]'`。

## GitHub Actions 部署

1. 新建仓库（**建议 private**），把本目录推上去。
2. 在仓库 Settings → Secrets and variables → Actions 配置 secrets：
   - 公共：`TELEGRAPH_TOKEN`
   - eh：`BOT_TOKEN`、`MAIN_CHANNEL_ID`、`EH_MEMBER_ID`、`EH_PASS_HASH`、`EH_CF_CLEARANCE`（可选）、`AGNES_API_KEY`、`AGNES_MODEL`、`AGNES_BASE_URL`（可选）
   - meirentu：`TG_TOKEN`、`TG_CHAT_ID_A`、`TG_CHAT_ID_B`、`VIP_LINK`（可选）
   - 4khd：`TG_TOKEN`、`TG_CHAT_ID_4KHD`、`TG_GROUP_ID`（可选）、`AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`（可选）
3. 调度频率（与原项目一致，可在各自 workflow 里改 cron）：
   - `eh.yml`：每 12 小时（`0 */12 * * *`）
   - `meirentu.yml`：每天 UTC 22:00 = 北京 6:00（`0 22 * * *`）
   - `k4hd.yml`：每天 UTC 12:00（`0 12 * * *`）
4. 每个 workflow 都支持 `workflow_dispatch` 手动触发，可传 `limit` 和 `dry_run`。
5. 每次跑完自动把 `state/` 的变化 commit + push（状态即仓库，天然去重）。

## 迁移旧状态

首次上线前跑一次，把三个旧项目的已发记录并入统一 `state/`，避免重复发布：

```powershell
python migrate_state.py --legacy E:\codex\picture --state state
```

然后**停掉旧项目**的 GitHub Actions / Gitea workflow 和本地定时任务，
再启用统一仓库（本地与 CI 同时跑会重复发布）。

## 注意事项

- **密钥安全**：本仓库务必 private；token / cookie 只放 GitHub secrets 或本地环境变量，不要提交。
  旧项目 HANDOFF 里出现过明文密钥，归档旧仓库时注意清理或设为 private。
- **e-hentai cookie**：`cf_clearance` 会过期，失效时从浏览器复制新值更新 secret；流量过大可能 509，代码会自动等 60s。
- **pixhost 限流**：上传带递增退避重试（最多 4 次）；连发太多仍可能失败，失败图片跳过不阻塞。
- **不要本地+CI 并行**：两边各自维护 state，同时跑会重复发布。
- **4khd 图床**：当前为 Telegraph 直嵌 4khd 原图（B2 免费档配额超限后的回退方案）；想换图床改 `sources/k4hd.py` 即可。
