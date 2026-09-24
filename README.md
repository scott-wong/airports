# airports

把 [OurAirports](https://ourairports.com/data/) 的公开机场数据定期采集进 InsForge 的独立
schema `airports`，支持每日重跑与更新，并为 `large_airport` / `medium_airport` 补充简体中文名
和中文城市名。

- 采集链路：Python 3.12 + `httpx` + InsForge Admin REST（`/api/database/advance/rawsql`），
  配置了 `AIRPORTS_DATABASE_DSN` 时可在 REST 不可用时回退直连 PostgreSQL。
- 中文名：`name_zh`（**5196/5281，98.4%**，含确定性合成与 LLM 兜底）、
  `municipality_zh`（服务城市，3084 条）、`location_zh`（机场所在地的聚居地，1363 条），
  每条都带来源字段（`wikidata:` / `wikipedia:` / `composite:` / `llm:`）。
- 与 `flight_ops` 完全独立：本仓库只读写 `airports` schema，不做双写。

术语见 [CONTEXT.md](./CONTEXT.md)，关键决定见 [docs/adr](./docs/adr)。

## 数据模型

`migrations/` 建出：

| 对象 | 用途 |
| --- | --- |
| `airports.airport` | 正式表，主键为 OurAirports 整数 `id`，`ident` 唯一 |
| `airports.airport_staging` | 每轮采集的落地区，校验后一次性合并 |
| `airports.airport_active` | 只读视图，`WHERE is_active`（不按 `type='closed'` 过滤） |
| `airports.collector_run` | 每轮采集的运行记录与差异计数 |
| `airports.schema_migrations` | 迁移版本与校验和 |

正式表字段 = OurAirports 数据字典的 19 个原始列（列名、语义照抄；CSV 的真实列顺序与数据
字典页不同，解析按列名而非位置） + 以下例外列：

`name_zh`、`name_zh_source`、`name_zh_updated_at`、`municipality_zh`、
`municipality_zh_source`、`location_zh`、`location_zh_source`、`row_hash`、`is_active`、
`first_seen_at`、`last_seen_at`、`deactivated_at`、`updated_at`、`source_snapshot_at`。

三点容易踩的坑：

- 数据字典写 `type` 允许 `closed_airport`，真实 CSV 里是 `closed`；CHECK 约束按真实数据。
- `is_active=false`（某轮快照里 `id` 消失）与 `type='closed'`（源端标注的关闭机场）是两个
  互不推导的维度，可以同时成立。
- `municipality_zh` 是“机场**服务**的城市”，`location_zh` 是“机场**所在地**的聚居地”，
  两者不是一回事（例：北京大兴机场 municipality=Beijing，location=九州镇）。

## 更新语义

1. 整份下载 CSV（12 MB，约 8.6 万行），解析校验（表头、类型受控值、重复 id/ident、行数下限）；
2. 全量写入 `airport_staging`；
3. 单条 SQL 按 `id` 合并进 `airport`：新增 / 变更 / 未变分别计数（变更 = 上游字段或任一中文字段
   变化），`updated_at` 只在变化时前移，`first_seen_at` 只写一次；
4. 本轮快照里缺席且仍 active 的行置 `is_active=false` 并写 `deactivated_at`（不物理删除）；
   重新出现时自动复活；
5. 写 `collector_run`，失败时把错误写进 `error_message` 并以非零退出码结束。

实机验证（2026-09-23，86,119 行）：

| 场景 | 结果 |
| --- | --- |
| 首次入库 | `inserted=86119` |
| 无变化重跑 | `unchanged=86119`，`updated=0` |
| 人为制造源端消失 | `deactivated=1` |
| 该行重新出现 | `reactivated=1` |
| 只改一条中文名 | `updated=1`，`name_zh_updated_at` 前移 |
| 新增 medium/location 中文名 | `updated=1972` |
| 合并 LLM/合成兜底中文名 | `inserted=7`，`updated=2040`，`unchanged=84079` |

## 中文名与中文城市名

数据来源与规则（`names refresh` 生成 `data/airport_names_zh.csv`，采集只读该文件）：

| 字段 | 来源（按优先级） | 规则 | 当前覆盖 |
| --- | --- | --- | --- |
| `name_zh` | ① Wikidata ② 确定性合成 ③ LLM 兜底 | ① IATA(P238) → ICAO(P239)，实体须为机场类且距离 ≤25km，标签按 `zh-cn > zh-hans > zh > 繁体` 取并转简体；② 英文名形如 `<地名> [International/Regional/…] <Airport/Air Base/…>` 且地名已有中文时直接拼；③ 仍无名字的交给大模型，不确定必须返回 `null` | **5196/5281** |
| `municipality_zh` | 英文维基百科跨语言链接 | 按 `municipality` 字段匹配条目（自动尝试去掉 `Shanghai (Pudong)` 这类后缀），要求分类属于居民点、排除消歧义页 | 3084 |
| `location_zh` | Wikidata P131 | 取机场 P131 中属于人类聚居地（Q486972 及其子类）的实体，多个人选时取人口最多者 | 1363 |

来源前缀可以直接过滤，例如只要权威来源：
`WHERE name_zh_source LIKE 'wikidata:%' OR name_zh_source LIKE 'wikipedia:%'`。

中文名有三份可追溯的产物：

- `data/airport_names_zh.csv`：主表（每个目标机场一行，含来源与状态），采集器只读它；
- `data/airport_names_llm.csv`：LLM 生成名的**独立存档**。`names refresh` 会自动合并它，
  所以在流水线里跑"不带 LLM 的刷新"不会丢掉这 1648 个名字；
- `name_zh_source` 前缀即来源分级：`wikidata:` / `wikipedia:`（权威）→ `composite:`（确定性合成）
  → `llm:`（模型生成）。

要点：

- 每个字段都有 `*_source` 记录来源（如 `wikidata:Q32190:zh-cn`、
  `wikipedia:en:London>zh`、`wikidata:Q36420:P131:Q125378:zh-cn`），可追溯、可复查；
- 兜底名一律带来源：`composite:municipality:<地名>` 是从已有中文地名拼出来的，
  `llm:codex:<模型>` 是大模型生成、并经本地校验（必须含中文、不能是英文原名、长度受限）；
  解析不到的留空并标 `unresolved`，省名/岛屿不会被当作城市名；
- 中文名的变更走 `names refresh` + git diff，不在采集链路里实时调用外部服务；采集时把
  该文件的 sha256 写进 `collector_run`。

## 用法

```bash
uv sync
uv run airports-collector migrate           # 建/升级 schema、表、视图、授权
uv run airports-collector validate-schema   # 校验对象与列是否齐全
uv run airports-collector names refresh     # 可选：重新生成中文名 CSV（约 8 分钟）
uv run airports-collector names refresh --llm-fallback --llm-model deepseek-v4.1-flash
                                            # 再补 LLM 兜底（约 30 分钟，本机 codex exec）
uv run airports-collector names extract-llm # 把主 CSV 里的 llm: 名字拆到 data/airport_names_llm.csv
uv run airports-collector collect           # 采集并入库（下载源站）
uv run airports-collector collect --csv /path/to/airports.csv   # 用本地 CSV
uv run airports-collector status            # 统计当前数据
uv run pytest                               # 单元测试
```

## 配置

默认从仓库根目录的 `.codex/config.toml` 读 InsForge 凭据（与 flight-data 共用键名），
优先级为 **环境变量 > `.env` > `.codex/config.toml` > 默认值**：

```env
API_BASE_URL=https://<your-insforge-host>
API_KEY=ik_...
AIRPORTS_SOURCE_URL=https://davidmegginson.github.io/ourairports-data/airports.csv
AIRPORTS_NAMES_FILE=data/airport_names_zh.csv
AIRPORTS_LLM_SUPPLEMENT_FILE=data/airport_names_llm.csv
AIRPORTS_BATCH_SIZE=1000
AIRPORTS_DATABASE_DSN=            # 可选，直连回退
```

`.codex/` 与 `.env` 已在 `.gitignore` 中，凭据不入库。

## 调度

每天一次就够（上游每日更新，增量很小）。仓库提供
[deploy/airports-collector.cron.example](./deploy/airports-collector.cron.example) 和
[deploy/com.airports.collector.plist.example](./deploy/com.airports.collector.plist.example)。

## 让前端用 SDK 读取

PostgREST 目前只暴露 `public, flight_ops`。要让应用用 InsForge SDK 读 `airports`，需要平台侧
（超级用户 `postgres`）执行一次 [ops/expose_airports_postgrest.sql](./ops/expose_airports_postgrest.sql)：
`ALTER ROLE postgres SET pgrst.db_schemas = 'public, flight_ops, airports'` 并重载配置。
`project_admin` 不是超级用户、也不继承任何角色，执行不了这条语句。表已给
`anon` / `authenticated` 授了只读 SELECT，且没有开启 RLS。

## 已知限制

- 仍 `unresolved` 的机场约 85 条：模型与权威来源都不确定时宁可留空。
- `llm:` 来源的中文名是生成值，不是权威译名；对精度敏感的用途请按来源前缀过滤。
- `municipality_zh` 只收录能确认是居民点的城市；省份、岛屿、行政区一律不写。
- `location_zh` 依赖 Wikidata P131，覆盖有限；它是“所在地”不是“服务城市”。
- 其余类型（small/heliport/seaplane/balloon/closed）不查中文名，`name_zh` 为空。
- 上游若改列名或新增列，采集会直接失败，而不是静默丢列。
