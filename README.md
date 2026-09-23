# airports

把 [OurAirports](https://ourairports.com/data/) 的公开机场数据定期采集进 InsForge 的独立
schema `airports`，支持每日重跑与更新，并为 `type = large_airport` 的机场补充简体中文名。

- 采集链路：Python 3.12 + `httpx` + InsForge Admin REST（`/api/database/advance/rawsql`），
  配置了 `AIRPORTS_DATABASE_DSN` 时可在 REST 不可用时回退直连 PostgreSQL。
- 中文字段：`name_zh`（大机场 1123/1174 已解析）、`municipality_zh`（v1 留空，见“已知限制”）。
- 与 `flight_ops` 完全独立：本仓库只读写 `airports` schema，不做双写。

术语见 [CONTEXT.md](./CONTEXT.md)，关键决定见 [docs/adr](./docs/adr)。

## 数据模型

`migrations/001_airports.sql` 建出：

| 对象 | 用途 |
| --- | --- |
| `airports.airport` | 正式表，主键为 OurAirports 整数 `id`，`ident` 唯一 |
| `airports.airport_staging` | 每轮采集的落地区，校验后一次性合并 |
| `airports.airport_active` | 只读视图，`WHERE is_active`（不按 `type='closed'` 过滤） |
| `airports.collector_run` | 每轮采集的运行记录与差异计数 |
| `airports.schema_migrations` | 迁移版本与校验和 |

正式表字段 = OurAirports 数据字典的 19 个原始列（列名、语义照抄；CSV 的真实列顺序与数据
字典页不同，解析按列名而非位置） + 以下例外列：

`name_zh`、`municipality_zh`、`name_zh_source`、`name_zh_updated_at`、`row_hash`、
`is_active`、`first_seen_at`、`last_seen_at`、`deactivated_at`、`updated_at`、
`source_snapshot_at`。

两点容易踩的坑：

- 数据字典写 `type` 允许 `closed_airport`，真实 CSV 里是 `closed`；CHECK 约束按真实数据。
- `is_active=false`（某轮快照里 `id` 消失）与 `type='closed'`（源端标注的关闭机场）是两个
  互不推导的维度，可以同时成立。

## 更新语义

1. 整份下载 CSV（12 MB，约 8.6 万行），解析校验（表头、类型受控值、重复 id/ident、行数下限）；
2. 全量写入 `airport_staging`；
3. 单条 SQL 按 `id` 合并进 `airport`：新增 / 变更 / 未变分别计数，`updated_at` 只在
   `row_hash` 或 `name_zh` 变化时前移，`first_seen_at` 只写一次；
4. 本轮快照里缺席且仍 active 的行置 `is_active=false` 并写 `deactivated_at`（不物理删除）；
   重新出现时自动复活；
5. 写 `collector_run`，失败时把错误写进 `error_message` 并以非零退出码结束。

实测（2026-09-23，86,119 行）：首次入库 `inserted=86119`；重跑 `unchanged=86119`；
人为插入的先消失行 `deactivated=1`、再次出现 `reactivated=1`；staging 每轮清空。

## 中文名

中文名来自 Wikidata，脚本自动生成并冻结成 `data/airport_names_zh.csv`（提交进仓库）：

1. 先按 IATA(P238)、再按 ICAO(P239) 匹配；实体必须属于机场类（`P31/P279* → Q1248784`），
   且坐标距离 ≤ 25km，命中多个等距实体则判为歧义、留空；
2. 标签优先级 `zh-cn > zh-hans > zh > zh-hant/zh-tw/zh-hk`，统一用 OpenCC 转简体，
   拒收含 4 个以上连续拉丁字母的混排标签（例如 `Akanu Ibiam國際機場`）；
3. 解析不到的留空并在 CSV 里标 `unresolved`，不做机器翻译、不猜。

当前覆盖：**1123/1174 大机场有中文名**（51 条 unresolved，主要是非洲/中亚小机场和两条
OurAirports 重复占位记录 `CA-1291`、`CA-1292`）。采集运行时把中文名与该文件的 sha256 一起写进
`collector_run`，中文名的变更走 `names refresh` + git diff，不在采集链路里实时调用外部服务。

## 用法

```bash
uv sync
uv run airports-collector migrate           # 建 schema/表/视图/授权
uv run airports-collector validate-schema   # 校验对象与列是否齐全
uv run airports-collector names refresh     # 可选：从 Wikidata 重新生成中文名 CSV
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

- `municipality_zh` 在 v1 留空：Wikidata `P131` 常给出比“服务城市”更细的行政区（北京大兴 → 九州镇），
  按城市名另做匹配的 SPARQL 查询会 504 超时，宁缺勿错。
- 其余机场类型（medium/small/heliport/seaplane/balloon/closed）不查中文名，`name_zh` 为空。
- 上游若改动列名或新增列，采集会直接失败，而不是静默丢列。
