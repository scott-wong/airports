# 用自定义 THREE.Points 画 8.6 万点，自建拾取

globe.gl 内置 points 层是"每个点一个圆柱 mesh"；虽然 `pointsMerge(true)` 能合并成一个对象
提升性能，但官方文档明确说明合并后 `onPointHover` / `onPointClick` 失效。8.6 万点既要不卡
又要有 hover/click，所以决定：把点渲染成自定义层里的**单个 THREE.Points**（一个 BufferGeometry、
一次 draw call，颜色/大小/透明度走 attribute + 自定义 shader，加性混合模拟发光，不叠后处理
bloom），拾取则用预建的 0.5° 经纬网格索引做屏幕空间最近邻（光标 10px 内），
筛选变化时只重建可见点的 buffer 与索引。测试用 globe.gl 自带的 `getCoords` 校验我们的
经纬度→三维坐标换算，避免点位整体偏移。
