# 星语项目后续开发 Skill 选型与执行路线

更新时间：2026-07-18  
目标项目：`F:\Skill-for-stars`

## 1. 选型结论

后续开发采用 6 个已安装 Skill。组合遵循三个原则：直接服务当前天文闭环、职责不重复、输出可以测试和追溯。

| Skill | 来源 | 核心职责 | 使用阶段 |
| --- | --- | --- | --- |
| `test-driven-development` | `obra/superpowers` | 每个功能先写失败测试，再写最小实现 | 每一天 |
| `astropy` | `K-Dense-AI/scientific-agent-skills` | 天文单位、时间、坐标、AltAz、角距离、FITS | 第 2、3、4、6 天 |
| `database-lookup` | `K-Dense-AI/scientific-agent-skills` | SIMBAD/SDSS 查询契约、输入清洗、来源与完整性记录 | 第 2、6 天 |
| `matplotlib` | `K-Dense-AI/scientific-agent-skills` | 可见性曲线、教学图表、PNG/PDF 导出 | 第 4、6 天 |
| `systematic-debugging` | `obra/superpowers` | 先定位根因，再处理时区、IERS、网络和转换异常 | 出现异常时 |
| `verification-before-completion` | `obra/superpowers` | 每日结束前运行完整验收，凭新证据声明完成 | 每一天结束时 |

安装位置：`C:\Users\yy\.codex\skills\<skill-name>`。

## 2. 在线来源快照

本次通过 GitHub API 核对来源，便于后续追踪 Skill 更新。

| 仓库 | 分支 | 核对提交 | 提交日期（UTC） | 许可证 | 核对时 Stars |
| --- | --- | --- | --- | --- | ---: |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | `main` | `3f825caafe14` | 2026-07-15 | MIT | 31,122 |
| [obra/superpowers](https://github.com/obra/superpowers) | `main` | `d884ae04edeb` | 2026-07-02 | MIT | 256,860 |

注意：Skill 是开发流程与参考资料，不等于 Python 依赖。项目仍需在自己的虚拟环境中安装并锁定 `astropy`、`astroquery`、`numpy`、`pandas` 和 `matplotlib`。

## 3. 第 2 天：目标解析 `target_resolver`

使用：`test-driven-development` + `database-lookup` + `astropy`。

具体任务：

1. 将项目 Python 要求调整为 3.11+。当前实际环境为 Python 3.12，可兼容 Astropy 7.2；项目现有 `>=3.10` 约束需要同步更新。
2. 安装并锁定 Astropy、Astroquery 等运行依赖。
3. 定义 `ResolvedTarget` 输出模型，至少包含标准名称、ICRS 赤经/赤纬（度）、天体类型、别名、来源、查询时间和原始查询词。
4. 通过 SIMBAD 解析 `M42`、`Orion Nebula` 等名称；为“猎户座大星云”等中文教学名称提供受控别名映射。
5. 对目标名做长度和字符校验，不把用户输入直接拼进 ADQL 或 shell。
6. 增加查询缓存、超时和结构化错误；SIMBAD 不可访问时不得伪造坐标。

验收门槛：

- M42 解析到猎户座大星云，并返回 ICRS 坐标和来源。
- 英文名、M 编号和受控中文名得到同一标准目标。
- 空目标、歧义目标、非法字符和网络失败都有自动化测试。
- 查询日志记录数据库、端点/接口、参数、访问时间和依赖版本。

## 4. 第 3 天：天象计算 `ephemeris_calculator`

使用：`test-driven-development` + `astropy`；出现异常时启用 `systematic-debugging`。

具体任务：

1. 将本地时间结合 `Asia/Shanghai` 转换为 UTC，并明确 Astropy `Time` 的时间尺度。
2. 使用 `EarthLocation` 表示北京观测点，使用 `SkyCoord` 和 `AltAz` 进行坐标转换。
3. 按 10 分钟间隔计算目标高度角、方位角、太阳高度、月亮高度及目标与月亮角距离。
4. 明确 IERS 数据策略：测试使用固定/离线数据，联网更新失败时给出警告和降级说明。
5. 输出 `intermediate/ephemeris.csv`，字段包含本地时间、UTC、高度角、方位角及太阳/月亮条件。

验收门槛：

- 跨午夜时间序列连续，起止点和采样数量正确。
- 角度全部携带单位后再导出，禁止混用弧度和度。
- 与 Stellarium 或另一独立来源抽查至少 3 个时刻，并记录允许误差和差异原因。
- 离线测试不依赖实时网络。

## 5. 第 4 天：观测计划与可视化

使用：`test-driven-development` + `astropy` + `matplotlib`。

具体任务：

1. 将判断阈值配置化，例如目标高度角不低于 30 度、太阳高度不高于 -12 度。
2. 将连续合格采样点合并为候选观测窗口，并保留不合格原因。
3. 月光影响先输出月相、月亮高度和角距离等证据，不用单一阈值武断判断“可见/不可见”。
4. 使用 Matplotlib 面向对象接口生成高度角曲线，标出阈值、暮光和推荐时段。
5. 使用非交互后端导出稳定尺寸的 PNG；关闭 Figure，避免批量运行内存泄漏。

验收门槛：

- 全晚不可见、多个分段窗口和恰好跨越阈值都有测试。
- PNG 文件存在、尺寸稳定且不是空白图。
- 标题、坐标轴、图例和时间标签无重叠。
- CSV 与图上数值来自同一份计算结果。

## 6. 第 5 天：流水线、日志与报告

使用：`test-driven-development` + `verification-before-completion`。

具体任务：

1. 用 `pipeline.py` 串联输入校验、目标解析、天象计算、观测窗口、制图和日志。
2. 生成 `run.json`、`result.json`、中间 CSV、图表、`report.md` 和 `review_checklist.md`。
3. 在运行清单中记录输入、依赖版本、查询来源、缓存命中、错误/降级状态和文件校验信息。
4. 报告明确区分计算事实、规则判断和人工复核项。
5. 扩展 CLI 为 `python -m starskill run <input.json>`。

验收门槛：

- M42 北京案例可一条命令端到端运行。
- 第二次运行能说明是否使用缓存。
- 图表失败时仍保留 JSON/CSV；数据查询失败时不生成虚假成功报告。
- 执行完整测试、CLI 实跑和输出目录检查后才能标记完成。

## 7. 第 6 天：扩展公开数据和第二、第三案例

使用：`database-lookup` + `astropy` + `matplotlib` + TDD。

具体任务：

1. 增加“月亮与木星位置关系”多目标案例，复用天象计算与角距离逻辑。
2. 增加 M51 公开数据案例，通过 Astroquery/公开档案查询图像或星表。
3. 保存查询参数、来源链接、访问时间、数据许可提示、波段和像素尺度。
4. 对图像只做可追溯的裁剪、亮度拉伸、比例尺和图注处理。

验收门槛：

- 外部数据响应被当作不可信数据解析，不能作为命令执行。
- 每次下载设置超时、大小限制和缓存键。
- 无数据或数据源不可访问时进入明确降级路径。
- 展示图保留来源与处理步骤。

## 8. 第 7 天：Skill 包装与答辩材料

现有系统 Skill：`skill-creator`、`pdf`、`presentations`。

具体任务：

1. 在核心 CLI 和测试稳定后，再用 `skill-creator` 编写给智能体使用的 `SKILL.md`。
2. Skill 说明只负责调用顺序、输入输出、错误处理和安全边界，详细 API 留在项目文档。
3. 使用 PDF/Presentations 工具生成不超过 20 页的技术报告和答辩演示。
4. 报告必须展示真实运行记录、测试结果、来源日志和人工复核入口。

## 9. 暂不采用的候选

| 候选 | 暂不采用原因 | 重新评估时机 |
| --- | --- | --- |
| `jupyter-notebook` | 核心产物必须是可测试、可复用的 Python 模块，不是 Notebook | 需要课堂探索式演示时 |
| `cli-creator` | 面向跨仓库全局 CLI；当前只需要仓库内命令 | CLI 稳定并准备全局安装时 |
| `scientific-visualization` | 偏出版级多面板图，当前教学曲线用 Matplotlib 足够 | 制作论文级图表时 |
| `playwright` | 当前没有网页界面 | 开发 Web 前端时 |

## 10. 每日统一工作规则

1. 先用 TDD 写一个能正确失败的行为测试。
2. 写最小实现使测试通过，再进行重构。
3. 外部查询必须记录来源、参数、时间和失败状态。
4. 遇到错误先复现和定位根因，不连续尝试多个猜测性修复。
5. 当天结束前重新运行完整测试、实际 CLI 和产物检查。
6. 只有新鲜验证输出全部通过，才能声明当天任务完成。

