# 中英双语与中文名来源徽章

界面文案、类型名、计数与日期用 i18next 维护 zh/en 两套（语言来源：URL `?lang=` → localStorage
→ 浏览器语言 → 默认 zh）；国家名不维护对照表，直接用浏览器内置
`Intl.DisplayNames(locale, {type: 'region'})`。数据侧双语规则：中文界面优先 `name_zh`、
`municipality_zh`、`location_zh`，缺失回退英文字段并显式标注"暂无中文名"；英文界面用原始
英文字段。因为 1648 条中文名是模型生成的，详情面板必须显示来源徽章（权威 / 合成 / AI 生成），
让读者自己判断可信度——这与数据侧"来源前缀可过滤"的设计一致。
