# 前端用 bun，站点用官方 Pages Actions 发布

本地与 CI 统一用 bun（`bun install` / `bun run build` / `bun test`，锁文件 `bun.lock` 入库），
不再引入 npm。站点发布走 GitHub 官方 Pages Actions（`configure-pages` +
`upload-pages-artifact` + `deploy-pages`），构建产物不进仓库历史；源码仓库已转为 public，
Pages 地址为 `https://scott-wong.github.io/airports/`，因此 Vite `base` 固定 `/airports/`。
流水线只在有数据变化时把刷新后的中文名 CSV 自动提交回 main，保持"CSV 是唯一事实来源"。
