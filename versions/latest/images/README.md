# 最新版图片

[tier_definitions.html](tier_definitions.html) 解释四个 Tier 与全部颜色标注。洋红色竖轴通过底层整体包络中点 G；俯视图中为十字。G 不表示重心。紫线是底层包络边界，C 点是每块砖的真实 XY 中心，橙点是满足 Tier 4 规则的上层中心。初始散件图用料盘参考 P。

每个 Tier 有独立 tier_1/…tier_4/ 目录，每个精选样例至少四张图。每个任务使用完整实例 ID 命名，里面 target.png / initial_to_target.png / layers.png / inspection.png 分别是目标三维图、初始到目标、分层图和四图检查。Tier 2 有 center_check.png；Tier 4 有 center_side.png 和 center_inspection.png。

当前每 Tier 精选 12 例；Tier 4 全部 100 例也包含中心检查。source/ 只用于对照图片；任务本体在 ../tasks/。默认按 symposium paper 风格绘制，静态图不认证接触物理。

重新生成到新目录：python scripts/render_gallery.py --output /tmp/benchmark_gallery_new
