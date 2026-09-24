# Context Map

## Contexts

- [机场参考数据](./CONTEXT.md)：采集 OurAirports 数据、生成中文名、写入 InsForge 的 `airports` schema。
- [机场地球](./web/globe/CONTEXT.md)：把参考数据发布成一个可缩放、可筛选、中英双语的 3D 地球页面。

## Relationships

- **机场参考数据 → 机场地球**：通过构建期快照单向传递。`airports-collector export-web` 把源 CSV 与中文名 CSV 合成
  `airports.json.gz`，展示端只读快照，不直连数据库、不持有任何凭据。
- 展示端**不反向写库**：它产生的筛选与选择状态只存在于浏览器 URL 里。
