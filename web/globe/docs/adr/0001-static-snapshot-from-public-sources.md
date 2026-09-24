# 展示端只吃构建期快照，周流水线只依赖公开源

InsForge 部署在内网（域名解析到 198.18.0.0/15 的代理地址），GitHub 托管 runner 连不上，因此
"流水线连库导出"会迫使要么自建内网 runner、要么把数据库暴露到公网。两条路都不划算。决定：
`export-web` 把公开源 CSV 与仓库内中文名 CSV 合成只读快照 `airports.json.gz`（数组行 + 顶层
`fields` 字段表 + 源文件 sha256），展示端只读该快照；每周一的流水线跑
`names refresh`（不带 LLM）→ `export-web` → `bun run build` → 官方 Pages Actions 发布，
不需要任何 secret。InsForge 仍由本地 `collect` 维护，与站点共用同一份源数据。

## 2026-09-24 补充：CI 默认不刷新中文名

实测 GitHub runner 直连 Wikidata/Wikipedia 会被限速（一次完整 refresh 超过 25 分钟仍未完成），
所以周流水线的职责收窄为"下载公开源 → export-web（用仓库内中文名 CSV）→ bun build → 发布"，
`refresh_names` 只在手动触发时可选执行。中文名仍以本机 `names refresh`（自动合并
`data/airport_names_llm.csv` 存档）后提交为准，保证 CSV 始终是唯一事实来源。
