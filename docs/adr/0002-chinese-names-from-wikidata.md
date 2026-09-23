# 中文名来自 Wikidata 的自动匹配，并冻结为仓库内版本化 CSV

OurAirports 没有中文名字段，而大机场中文名是公开知识、变化缓慢。选择用 Wikidata 标签自动
生成：IATA(P238) → ICAO(P239) 匹配，要求实体属于机场类且坐标距离 ≤25km，标签按
zh-cn > zh-hans > zh > 繁体转简体 的顺序取值；无法确认的留空并标记 `unresolved`。生成结果
冻结成 `data/airport_names_zh.csv` 提交进仓库，采集时只读该文件，不在采集链路里调用外部
翻译或 LLM —— 目的是让每条中文名可 diff、可复现、可追溯，避免静默错配（例如把 ABQ 匹配到
科特兰空军基地这类错误实体）。
