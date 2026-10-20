# 新旧版本与图片位置

- 最新版完整任务：versions/latest/tasks/，400 个。
- 最新版图片：versions/latest/images/index.html；分成 tier_1/…tier_4/，每 Tier 12 个精选多视图样例；Tier 4 包含全部 100 个中心检查。
- 初次生成版完整任务：versions/initial/tasks/，400 个。
- 初次生成版图片：versions/initial/images/index.html，24 个最初论文风格样例。
- 远端原始数据：根目录 tasks/，400 个历史任务，与初次生成版不同。

源码在 scripts/，资源在 assets/meshes/，测试在 tests/，详细生成约定在 docs/。实际使用最新版本，不把历史数据混入当前评估。
