# 机场地球（web/globe）

把 `airports` 参考数据渲染成一张可缩放、可筛选、中英双语的 3D 地球，部署到
`https://scott-wong.github.io/airports/`。

- 渲染：globe.gl（three.js）球体 + 大气辉光 + 星空；点位是**单个 THREE.Points**（一次 draw call、
  自定义 shader、加性混合），悬停/点击用 0.5° 经纬网格 + 屏幕空间最近邻拾取（见 `docs/adr/0002`）。
- 数据：构建期快照 `public/airports.json.gz`，由 `airports-collector export-web` 生成，
  **页面不连数据库、不需要任何凭据**（见 `docs/adr/0001`）。
- 双语：i18next（zh/en），语言优先级 `?lang=` → localStorage → 浏览器语言 → zh；国家名用
  `Intl.DisplayNames`；中文名带来源徽章（权威 / 合成 / AI 生成，见 `docs/adr/0003`）。
- 工具链：bun + Vite + React + TypeScript + Tailwind 3.4 + vitest；发布用官方 Pages Actions（见 `docs/adr/0004`）。

## 本地开发

```bash
# 1) 先生成快照（在仓库根目录）
uv run airports-collector export-web

# 2) 前端
cd web/globe
bun install
bun run dev            # http://localhost:5174/airports/
bun test               # 单元测试（筛选/解析/坐标/拾取/i18n 词典）
bun run build          # 类型检查 + 产物构建到 dist/
bun run bench          # 8.6 万点性能基准（本地跑，不进 CI）
```

## 快照契约（schemaVersion = 1）

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-09-24T05:37:44Z",
  "source": { "url": "...", "sha256": "...", "rowCount": 86126 },
  "names":  { "file": "data/airport_names_zh.csv", "sha256": "...", "rowCount": 5281 },
  "fields": ["id", "ident", "type", "name", "...", "name_zh_source", "location_zh_source"],
  "rows": [[6523, "00A", "heliport", "Total RF Heliport", 40.070985, -74.933689, null, null]]
}
```

- 行是数组，`fields` 是字段表；解析在 `src/lib/snapshot.ts`，遇到未知 `schemaVersion` 直接报错。
- `public/manifest.json` 是同一份数据的摘要（行数、按类型计数、sha256），方便核对。
- 两个文件都是构建产物，不入库；流水线里现生成。

## 交互

| 操作 | 效果 |
| --- | --- |
| 拖拽 / 滚轮 | 旋转 / 缩放（缩放到 0.55 高度可看城市级） |
| 悬停点 | 右侧面板显示该机场（未选中时跟随鼠标） |
| 点击点 | 选中并固定详情；点空白处取消 |
| 空格键 | 暂停 / 恢复自动旋转 |
| `Esc` | 取消选中 |
| 右上角 ZH/EN | 切换语言并记住 |

筛选条件（类型、国家、关键字、仅有中文名、仅定期航班）会写进 URL，可直接分享：
`/?type=large_airport,medium_airport&country=CN&q=大兴&lang=zh`。

## 性能预算（见 ADR-0002）

- 快照 4.1 MB gzip，一次加载；86,126 点一次 draw call；
- 目标：首屏 ≤2s、筛选响应 ≤100ms、悬停拾取 ≤16ms、全开 ≥45fps（M1/1440p）；
- 相机距离 >300 时自动只画 large/medium/seaplane/balloon，避免小点糊成一团；
- 本机实测（M 系列，`bun run bench`）：几何构建 12.1ms、默认筛选 3.6ms、全类型+关键字筛选 42.5ms、
  拾取网格 6.5ms、1000 次 hover 拾取 2.9ms、8.2MB 快照解析 54ms。

## 调试

页面把 globe.gl 实例挂在 `window.__airportGlobe` 上（`getScreenCoords`/`toGlobeCoords`/`pointOfView`
都在上面），方便用浏览器控制台或自动化脚本定位点位、复现拾取问题。

## 部署

`.github/workflows/pages.yml`：每周一 03:00（Asia/Shanghai）或手动触发，依次
`export-web`（用仓库内的中文名 CSV）→ `bun install && bun run build` → 官方 Pages Actions 发布；
若数据文件有变化会提交回 `main`。

- 默认**不在 CI 里刷中文名**：GitHub runner 访问 Wikidata/Wikipedia 会被限速（实测 25 分钟仍未完成）。
  中文名更新走本机 `uv run airports-collector names refresh`（自动合并 LLM 存档）后提交；
  确实想在 CI 里刷时，手动触发 workflow 并勾选 `refresh_names`。
- 站点数据 = 公开源 CSV（每次都重新下载）+ 仓库内中文名 CSV，因此没有内网依赖、没有 secret。
