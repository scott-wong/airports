# 机场参考数据

把 OurAirports 的公开机场数据采集为 InsForge 中 `airports` schema 下的可更新参考数据，并为大机场补充中文名。

## Language

**机场 (Airport)**:
OurAirports `airports.csv` 中的一条机场记录，在本地以 OurAirports 的持久整数 `id` 标识。
_Avoid_: 站点、节点、POI

**机场身份 (Airport identity)**:
OurAirports 的整数 `id`，即使机场代码变化也保持不变。
_Avoid_: ident、代码、IATA、ICAO

**ident**:
OurAirports 对外可见的字符串标识，有 ICAO 时等于 ICAO，否则为本地码或内部生成码；它会变化，因此不是身份。
_Avoid_: 主键、机场 ID

**类型 (type)**:
OurAirports 的机场类型受控取值：`large_airport`、`medium_airport`、`small_airport`、`heliport`、`seaplane_base`、`balloonport` 和 `closed`。官方数据字典把最后一项写作 `closed_airport`，但数据文件中实际值为 `closed`。
_Avoid_: 状态、类别

**大机场 (large_airport)**:
需要中文名的机场类型；其余类型的中文名按可得性补充。

**中文名 (name_zh)**:
机场名的简体中文写法，取自中文标签并按大陆用词规范化为简体。
_Avoid_: 译名、别名、name_cn

**城市中文名 (municipality_zh)**:
机场服务城市 (`municipality`) 的简体中文写法。

**失活 (inactive)**:
某轮采集中源 CSV 不再包含该机场 `id` 的本地状态；与源端类型 `closed` 是两回事，二者可以同时成立。
_Avoid_: 关闭、删除、下线

**采集轮次 (collector run)**:
一次完整的源快照下载、入库与差异统计过程。
_Avoid_: 任务、作业、批次

**中文名文件 (airport names file)**:
仓库内版本化的 `data/airport_names_zh.csv`，是机器可读的中文名唯一事实来源；采集只读取它，不实时翻译。
_Avoid_: 翻译缓存、字典
