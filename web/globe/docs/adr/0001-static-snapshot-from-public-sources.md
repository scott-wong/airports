# 展示端只吃构建期快照，周流水线只依赖公开源

InsForge 部署在内网（域名解析到 198.18.0.0/15 的代理地址），GitHub 托管 runner 连不上，因此
"流水线连库导出"会迫使要么自建内网 runner、要么把数据库暴露到公网。两条路都不划算。决定：
`export-web` 把公开源 CSV 与仓库内中文名 CSV 合成只读快照 `airports.json.gz`（数组行 + 顶层
`fields` 字段表 + 源文件 sha256），展示端只读该快照；每周一的流水线跑
`names refresh`（不带 LLM）→ `export-web` → `bun run build` → 官方 Pages Actions 发布，
不需要任何 secret。InsForge 仍由本地 `collect` 维护，与站点共用同一份源数据。
