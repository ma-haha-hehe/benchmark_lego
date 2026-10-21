# 任务生成、渲染与评估接口

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

从仓库根目录运行脚本，使用 Python 3.10 或更新版本。当前任务入口是 `versions/latest/tasks/`；旧版在 `versions/initial/`。生成和验证需要 `requirements.txt`，渲染额外需要 `requirements-visualization.txt`。

## 生成与验证

```sh
python3 scripts/generator.py --task_class all --num_samples 100 --output_dir /tmp/workbenchmark_tasks_new
python3 scripts/verifier.py --benchmark_root /tmp/workbenchmark_tasks_new
python3 -m unittest discover -s tests -v
```

`--num_samples` 是每个类别的任务数，`all` 加 100 会生成 400 个任务。已有任务默认拒绝覆盖；检查新目录后再决定是否替换版本。单实例检查可使用：

```sh
python3 scripts/verifier.py --instance_dir versions/latest/tasks/simple_multi_brick_stack/simple_multi_brick_stack_001
```

静态验证覆盖格式、清单一致性、网格、支撑、连通、场景间距和简化抓取空间，不调用机器人或接触物理仿真。种子调度和几何约定见 [generation_contract.md](../docs/generation_contract.md)。

## 图像生成

```sh
python3 scripts/render_gallery.py --output /tmp/workbenchmark_gallery_new
```

默认读取当前版本，使用论文风格，每个 Tier 展示 12 个精选样例，并为全部 Tier 4 任务绘制中心检查。`--tiers 2` 可只生成 Tier 2；`--style stl` 可使用实际网格。输出目录必须尚不存在，以免混入旧版图片。

渲染器会重新绘制全部视图。洋红轴固定在底层包络中点 G，紫线标包络，C 编号标砖中心，橙点标 Tier 4 合格中心。`manifest.csv` 保留任务与图片映射；逐次渲染审计输出只在本地使用。标注含义见 [tier_definitions.md](../docs/tier_definitions.md)。

主示例统一使用 `target.png`；paper 风格固定方位角 −60°、仰角 25°，与既有 Tier 1–3 图像一致。渲染器为 Tier 4 全部 100 个任务生成这一主视图，`center_side.png` / `center_inspection.png` 单独作为辅助检查，不能替代 gallery 缩略图。

## 接入评估

`run_eval.py` 是适配模板。使用前需实现：

- `BenchmarkEnvAdapter.reset_with_instance`：创建初始场景并返回观测。
- `BenchmarkEnvAdapter.step_env`：执行动作并返回观测、结束标记和附加信息。
- `BenchmarkEnvAdapter.get_current_world_state`：读取用于终态检查的积木位姿。
- `MethodRunner.act`：根据观测输出策略动作；`setup_instance` 可初始化规划或策略连接。

`build_env` 和 `build_method` 是环境与方法入口；现有 `ours`、`pi0` 与 `dry_run` 名称不包含可直接运行的机器人或策略实现。完成适配后，可通过下列形式运行，并将结果写入本地 `results/`：

```sh
mkdir -p results
python3 scripts/run_eval.py --benchmark_root versions/latest/tasks --method ours --max_instances 5 --use_verifier --output_csv results/sample.csv
python3 scripts/summarize_results.py --csv results/sample.csv
```

逐实例 CSV 包含成功标记、执行与规划时间、完成块数、进度、步数、抓取失败计数和失败类别。默认位置容差为 15 mm，朝向容差为 10°；这只是模板配置，开展实际装配实验时应按物理接口明确设置。该脚本的位姿匹配不能代替接触稳定性或真实释放检查。

配套 [robot_korea](https://github.com/ma-haha-hehe/robot_korea) 提供独立的 MuJoCo 控制与抽样评估入口，使用自身的接触检查和接受标准。引用结果时应注明具体执行器及配置，避免混用两个接口的指标。运行日志、结果 CSV 与调试文件保留在本地；公开数据中的 manifest 和任务 metadata 用于复现输入。
