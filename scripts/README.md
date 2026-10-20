# 脚本用途

| 脚本 | 用途 |
|---|---|
| generator.py | 生成任务；默认输出 versions/latest/tasks/ |
| geometry.py | 共享积木尺寸、支撑、边界与中心规则 |
| verifier.py | 校验任务 YAML 与静态几何 |
| render_gallery.py | **正式图片生成入口**，按 Tier 和实例整理，多视图、每 Tier 默认 12 个精选样例 |
| visualize_task.py | 三维绘图、分层图和组合图工具；CLI 转到正式入口 |
| visualize_tier4_centres.py | Tier 4 中心边界绘图工具；CLI 转到正式入口并选择 Tier 4 |
| run_eval.py | 评估流程；环境和策略接口需要接入实际实现 |
| metrics.py | 评估指标辅助 |
| summarize_results.py | 汇总评估结果 |

从仓库根目录运行脚本。当前任务入口是 versions/latest/tasks/；旧版在 versions/initial/。

最新版检查标注：render_gallery.py 会重新绘制全部视图，不复用旧图片缓存。洋红轴固定在底层包络中点 G，紫线标包络，C 编号标砖中心，橙点标 Tier 4 合格中心；输出 structure_axis_audit.json 与 tier_definitions.html。说明见 ../docs/tier_definitions.md。
