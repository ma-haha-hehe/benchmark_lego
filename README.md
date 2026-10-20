# WorkBenchMark：任务、图片与脚本

[四个 Tier 的定义与标注读图](versions/latest/images/tier_definitions.html) · [中文定义文档](docs/tier_definitions.md)

**实际使用最新版：`versions/latest/`。** [打开四个 Tier 的图片入口](versions/latest/images/index.html) · [新旧版本导航](versions/index.html)

## 仓库结构

```text
Workbenchmark/
├── versions/
│   ├── latest/                 当前实际使用的版本
│   │   ├── tasks/              400 个完整任务，Tier 1–4 各 100 个
│   │   ├── images/
│   │   │   ├── tier_1/         12 个精选样例，多视图
│   │   │   ├── tier_2/         12 个精选样例，共同中心检查
│   │   │   ├── tier_3/         12 个精选样例，桥接与分层检查
│   │   │   └── tier_4/         12 个精选样例＋全部 100 个中心边界检查
│   │   └── validation/         任务、图像和中心坐标的核对记录
│   └── initial/                初次生成版本，完整任务与最初图片
├── tasks/                      远端原始的 400 个任务，只作历史存档
├── scripts/                    生成、校验、渲染、评估脚本
├── assets/meshes/               原始积木 STL 网格
├── tests/                      生成器与校验器测试
├── docs/                       详细几何、格式和生成约定
└── 版本导航.md                  中文路径说明
```

## 每个 Tier 的对应任务与图片

| Tier | 最新任务目录（在 versions/latest/tasks/ 下） | 最新图片入口 | 核心规则 |
|---|---|---|---|
| 1 | `two_brick_stack/` | [Tier 1](versions/latest/images/tier_1/index.html) | 2 块，同类型、同中心、固定朝向 |
| 2 | `simple_multi_brick_stack/` | [Tier 2](versions/latest/images/tier_2/index.html) | 2–5 块，以 2–3 块为主，同类型、XY 中心一致，朝向只允许 0°/90° |
| 3 | `simple_shape_assembly/` | [Tier 3](versions/latest/images/tier_3/index.html) | 3–12 块，桥接连接，砖体不超出底层整体边界 |
| 4 | `balanced_order_sensitive/` | [Tier 4](versions/latest/images/tier_4/index.html) | 3–12 块，至少一块上层砖的 XY 中心在底层边界上或外部 |

Tier 2 的 100 个任务为 **2 块 43 个、3 块 42 个、4 块 8 个、5 块 7 个**，即 85% 为 2–3 块、15% 为 4–5 块。允许 2 块后，其同朝向样例可能与 Tier 1 外观重叠；Tier 2 仍采用独立 0°/90° 朝向策略。

Tier 3/4 数据各保持 **80% 为 3–5 块、15% 为 6–8 块、5% 为 9–12 块**，最多三层、直线平行布局。精选图像优先展示小砖数，同时保留范围检查样例；精选样例比例不等于完整数据集比例。

每个精选样例使用任务实例 ID 命名的独立图片文件夹：

- `target.png`：目标三维图。
- `initial_to_target.png`：同一组积木从初始摆放到目标装配。
- `layers.png`：逐层 XY 检查图。
- `inspection.png`：正反目标视图、分层图、初始摆放的四图检查。
- Tier 2 的 `center_check.png`：共同中心与朝向检查。
- Tier 4 的 `center_side.png`、`center_inspection.png`：中心与底层边界检查。
- `source/`：对应样例的 YAML 对照副本；实际 benchmark 输入使用 `versions/latest/tasks/`。

最新版全部图片标注共同结构参考轴 G（洋红）、底层整体包络边界（紫色）、各砖中心 C1…CN、Tier 4 合格上层中心（橙色）及世界 X/Y 方向（青色）。G 取底层包络中点，各层共用同一个 G；G 不是重心。初始散件图使用料盘参考点 P。

TOTAL 表示实体积木数量，凸点不额外计数。不同视图展示同一个任务，不相加。默认采用 symposium paper Fig. 1/3 的纯色、实心凸点、灰色网格和黑轮廓风格。

## 使用

在仓库根目录安装相应依赖：

```sh
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-visualization.txt
python3 scripts/verifier.py --benchmark_root versions/latest/tasks
python3 -m unittest discover -s tests -v
```

生成新数据或图片时使用新的输出目录，检查后再替换当前版本：

```sh
python3 scripts/generator.py --task_class all --num_samples 100 --output_dir /tmp/benchmark_tasks_new
python3 scripts/render_gallery.py --output /tmp/benchmark_gallery_new
```

生成器默认位置和渲染器输入都是 `versions/latest/tasks/`。每个任务有三个 YAML：`final_product.yaml`（目标）、`scene_init.yaml`（初始场景）、`metadata.yaml`（任务信息与规则）。位置单位为米，旋转单位为弧度，XY 原点在砖体中心，Z 是砖体底面。

## 历史数据与验证范围

`versions/initial/` 是第一次生成的完整 400 个任务及其最初论文风格预览。根目录 `tasks/` 是远端原始数据，与初次生成版不同，两者都保持历史内容。

当前验证覆盖静态几何、支撑率、场景间距和简化抓取约束；图片不认证接触物理或实机平衡。`run_eval.py` 的环境和策略接口仍需接入实际仿真/基线。详细约定在 [docs/generation_contract.md](docs/generation_contract.md)。
