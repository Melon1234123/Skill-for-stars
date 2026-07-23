# StarSkill：面向 AI 的天文实训技能包

StarSkill 是一个可安装、可复现、可审计的天文实训工具包。它把目标解析、天象计算、观测窗口规划、公开数据获取和结果复核组织成可以被 AI Agent 稳定调用的工作流。

项目面向天文课堂、科普活动和科研入门训练。它不是开放式天文聊天助手，也不替代教师、科普人员或研究者对科学事实、观测条件和安全事项的最终判断。

## 产品闭环

一个任务从结构化 JSON 输入开始，经过 CLI 和 `run-starskill` Skill 调用天文工具，最终生成可检查的结果包：

```text
任务 JSON
  -> 输入校验
  -> 目标解析
  -> 天象与坐标计算
  -> 可观测窗口规划
  -> 可选的公开数据获取
  -> JSON / CSV / PNG / Markdown 产物
  -> run.json、来源、哈希和人工复核清单
```

核心原则是保留中间结果和失败证据，而不是只返回一段自然语言结论。外部 Agent 评测也必须检查真实命令、退出码、工具调用记录和实际文件。

## 已实现能力

- `validate`：校验目标、地点、时间、时区和观测任务输入。
- `resolve`：通过 SIMBAD 解析目标名称或坐标，输出标准名称、坐标、类型、别名、来源和缓存记录。
- `ephemeris`：使用 Astropy 计算目标、太阳和月亮的 AltAz 位置及相关天象信息。
- `plan`：根据目标高度角、太阳高度角、月亮影响等规则生成候选观测窗口和可视化曲线。
- `run`：串联输入校验、目标解析、星历计算、观测规划、制图、报告和复核清单，生成完整审计包。
- `relationship`：计算上海案例中月亮与木星的天空位置关系，避免把视线角距离误解为真实空间距离。
- `fetch-image`：从 SDSS DR18 获取受大小、超时、MIME、JPEG 和尺寸校验约束的 M51 图像，并保留来源和处理元数据。
- 评测工具：提供 Worker/Reviewer 提示词、案例清单、真实运行证据回放、机器检查和分项评分。

## 三个可复现案例

| 案例 | 输入 | 工作流 | 主要产物 |
| --- | --- | --- | --- |
| 北京 M42 观测 | `examples/observation_m42_beijing.json` | `run` | `run.json`、`result.json`、星历表、可见性表、曲线、报告、复核清单 |
| 上海月亮-木星关系 | `examples/moon_jupiter_shanghai.json` | `relationship` | `relationship.csv`、`relationship.json` |
| M51 公开图像 | `examples/m51_sdss_image.json` | `fetch-image` | `data/m51_sdss.jpg`、`figures/m51_display.png`、`image_metadata.json` |

## 安装

要求 Python 3.11 或更高版本。

```powershell
git clone https://github.com/Melon1234123/Skill-for-stars.git
cd Skill-for-stars

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
```

macOS 或 Linux 使用：

```bash
python3 -c 'import sys; raise SystemExit("StarSkill requires Python 3.11 or newer" if sys.version_info < (3, 11) else 0)'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ".[dev]"
```

如需使用 Skyfield/DE421 独立交叉验证脚本，再安装验证依赖：

```bash
python -m pip install ".[validation]"
```

## 快速开始

先运行全部测试：

```bash
python -m pytest -q
```

校验北京 M42 输入：

```bash
python -m starskill validate examples/observation_m42_beijing.json
```

运行完整观测工作流。每次运行应使用新的输出目录：

```bash
python -m starskill run examples/observation_m42_beijing.json \
  --output-dir runs/m42-beijing \
  --cache-dir cache/targets
```

`run.json` 是完整运行的权威状态和产物清单。成功运行通常还会包含：

```text
runs/m42-beijing/
  input.json
  run.json
  result.json
  report.md
  review_checklist.md
  intermediate/
    target_resolved.json
    ephemeris.csv
    ephemeris.json
    visibility.csv
  figures/
    visibility_curve.png
```

## CLI 示例

目标解析：

```bash
python -m starskill resolve M42 \
  --cache-dir cache/targets \
  --output runs/m42-resolve/target_resolved.json
```

单独计算星历：

```bash
python -m starskill ephemeris examples/observation_m42_beijing.json \
  --target-file runs/m42-resolve/target_resolved.json \
  --output runs/m42-ephemeris/ephemeris.csv \
  --metadata runs/m42-ephemeris/ephemeris.json
```

单独规划观测窗口：

```bash
python -m starskill plan runs/m42-ephemeris/ephemeris.json \
  --output runs/m42-plan/visibility.csv \
  --metadata runs/m42-plan/result.json \
  --figure runs/m42-plan/visibility_curve.png \
  --min-target-altitude-deg 30 \
  --max-sun-altitude-deg -12
```

月亮-木星关系：

```bash
python -m starskill relationship examples/moon_jupiter_shanghai.json \
  --output runs/moon-jupiter/relationship.csv \
  --metadata runs/moon-jupiter/relationship.json
```

SDSS M51 图像：

```bash
python -m starskill fetch-image examples/m51_sdss_image.json \
  --output-dir runs/m51-sdss \
  --cache-dir cache/sdss
```

所有命令的参数、产物和退出码见 [`skills/run-starskill/references/cli-contract.md`](skills/run-starskill/references/cli-contract.md)。错误以结构化 JSON 写入 stderr，外部服务失败不能被伪造为成功。

## AI Agent Skill

Agent 入口位于 [`skills/run-starskill/SKILL.md`](skills/run-starskill/SKILL.md)。它规定了：

- 如何选择完整工作流或单个 CLI 阶段；
- 如何复用匹配的示例输入并为新任务先做校验；
- 如何保存命令、输出目录、缓存状态和真实退出码；
- 如何检查 `run.json`、图像元数据、文件完整性和人工复核项；
- 哪些判断不能自动承诺，例如天气、云量、地平线遮挡、设备可用性和观测安全。

仓库内的 CLI 不会创建子 Agent，也不会调用 LLM API。最终评测中的 Worker 和 Reviewer 编排由仓库外的评测 harness 完成。

## 外部 Agent 评测

评测重点是一个明确任务能否形成稳定闭环，而不是功能数量。评测会检查真实文件、真实退出码和可复现证据。

### 固定任务

- 3 个 core 案例：M42 观测、M51 SDSS 图像、月亮-木星关系；
- 3 个 Worker 角色：teacher、outreach、research；
- 每个 core 案例独立运行 3 次，共 9 次 Worker 运行；
- 6 个 variant 案例检查参数变化、缓存复用和边界条件；
- open task 单独报告，不影响固定任务的通过线。

第一阶段的 Worker 运行彼此独立，避免角色互相掩盖问题；全部 Worker 完成后再进行一轮交叉复核。Reviewer 轮换关系固定为：

```text
teacher reviewer  -> outreach Worker
outreach reviewer -> research Worker
research reviewer -> teacher Worker
```

### 通过门槛

- core 平均基础分至少 `80/100`；
- 每个固定 core 案例的 3 次运行总体标准差不超过 `5`；
- variant 硬门槛通过率至少 `90%`，当前 6 个 variant 需要全部通过；
- 硬门槛失败不能用 Reviewer 宽容或加分抵消；
- 工程加分最多额外 `10` 分，用于接口标准化、运行加速、可复现重构等真实证据。

评测输入、提示词、案例和回放命令位于 [`evaluation/`](evaluation/)。外部运行证据推荐写入被 `.gitignore` 排除的 `evaluation-runs/`，避免把生成结果和凭据提交到仓库。

## 目录结构

```text
src/starskill/                         CLI 和天文工作流实现
skills/run-starskill/                  Agent Skill 入口和 CLI 契约
evaluation/cases/                      core、variant、failure、open 案例
evaluation/prompts/                    Worker、Reviewer、Adjudicator 提示词
evaluation/tasks/                      可直接回放的任务输入
evaluation/reports/                    评测报告目录说明
scripts/evaluate_starskill.py          replay 和 aggregate 评测工具
examples/                              三个主要案例输入
tests/                                 单元、CLI、回放和评测测试
docs/starskill-evaluation/             评测设计、修复简报和复核历史
docs/                                  分阶段技术文档和最终技术报告
```

## 数据、缓存与可复现性

- Astropy 负责主要坐标、时间和太阳系计算；Astroquery 负责 SIMBAD 查询；Matplotlib 负责绘图。
- SIMBAD 和 SDSS 都被视为不可信的外部服务，查询有超时、缓存、响应校验和来源记录。
- `run.json` 记录运行状态、依赖版本、来源、缓存命中、问题和产物 SHA-256。
- 缓存、运行结果、评测运行目录和虚拟环境默认被 `.gitignore` 排除。
- Skyfield/DE421 只作为独立交叉验证，不替代生产路径的 Astropy 结果。

## 任务边界与人工复核

StarSkill 可以计算几何可见性和生成候选观测窗口，但不等于天气预报、地平线评估、设备检查或安全许可。使用者仍需检查：

- 当地天气、云量和光污染；
- 地平线遮挡、设备状态和实际视场；
- 教学活动中的监督与观测安全；
- 公开数据的来源、授权和展示方式；
- 月亮与木星的角距离是天空中的视线关系，不是两者真实空间距离。

太阳观测等安全敏感任务必须保留人工确认。项目不会用编造的坐标、图像、来源、缓存命中或成功状态补全失败结果。

## 相关文档

## 本机 Python 星图

`sky-chart` 是本机可视化星图工作流，要求 Python 3.11 或更高版本。下面是可直接
复制的 macOS/Linux 全新克隆流程；它不复制缓存、`runs/`、`.env` 或任何可选的
outreach 配置：

```bash
starskill_clone_dir=$(mktemp -d)
git clone https://github.com/Melon1234123/Skill-for-stars.git "$starskill_clone_dir"
cd "$starskill_clone_dir"

python3 -c 'import sys; raise SystemExit("StarSkill requires Python 3.11 or newer" if sys.version_info < (3, 11) else 0)'
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
.venv/bin/starskill sky-chart --open
```

如果 `python3` 不是 Python 3.11 或更高版本，请先安装并选择兼容的 Python
解释器（例如 `python3.12`），再用该解释器执行上面的前三条命令。安装使用标准
wheel，而非 editable 安装，确保命令行入口在新的虚拟环境中可以直接导入包。

默认服务只监听回环地址 `127.0.0.1` 的端口 `8000`。`--open` 会在健康检查通过后
打开本机浏览器；不使用该选项时，手动访问 `http://127.0.0.1:8000/`。可用
`--port 8000` 显式指定端口（有效范围为 1024--65535），并在另一终端确认：

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

响应 `{"status":"ok"}` 表示本机服务可用。

### 星表与导出

页面可选择 `auto`、`bundled` 或 `full` 星表模式。`bundled` 始终使用随包亮星表；
`auto` 在本机存在已验证的完整星表时使用它，否则退化为随包亮星表并报告
`degraded`；`full` 只接受已验证的本地完整星表。默认缓存目录为
`cache/sky-chart`。

只有下列用户显式执行的下载操作可以访问固定且已验证的 HYG 4.1 数据源；普通启动、
渲染和导出均不访问该数据源。下载完成后才可使用完整密度星表：

```bash
.venv/bin/starskill sky-chart --download-catalog
```

每次渲染都会返回一个不透明的 render ID，并给出由该 ID 关联的同源 PNG 与 JSON
导出地址。JSON 中的 `render.png_sha256` 是对应 PNG 字节的 SHA-256，可用于核对
导出的配对关系和完整性。

### 边界与隐私

本机页面不会上传数据，不请求浏览器定位或其他浏览器权限；服务仅监听回环地址且不
启用 CORS。它是基于输入时间和地点的星图，不模拟 Stellarium，不保证实际天气、
可见性或观测安全，也不使用实时光污染数据。请由人类核对天气、云量、地平线遮挡、
设备和现场安全。

### Optional outreach enhancements

No API key, Black Marble snapshot, or desktop Stellarium installation is
required for `sky-chart`. The following environment variables enhance only
existing optional outreach or MCP routes; they are not prerequisites for the
local visual sky chart:

| Variable | Optional effect when configured | Behavior when absent |
| --- | --- | --- |
| `STARSKILL_NASA_API_KEY` | Allows the NASA APOD provider to request its optional feature. Keep the key in the local process environment only. | The NASA panel is explicitly `unavailable`; the provider makes no request without a key. |
| `STARSKILL_LIGHT_POLLUTION_SNAPSHOT` | Points to a local, versioned NASA Black Marble snapshot. | The light-pollution panel is explicitly `unavailable`; it does not claim a live measurement. |
| `STARSKILL_STELLARIUM_BASE_URL` | Optionally overrides the local loopback desktop Stellarium RemoteControl origin. | `sync_stellarium` keeps its default `http://127.0.0.1:8090`; if the desktop service is absent or unreachable, it returns structured `ok: false, error: connection_error` without blocking core workflows. |

The following APOD check is deliberately opt-in and is not part of the offline
test suite or the fresh-clone acceptance procedure. Run it only after setting a
nonempty private key. It never prints the key; `fresh`, `cached`, and
`unavailable` are all valid outcomes, with `unavailable` denoting service
degradation rather than a CI failure:

```bash
if [ -n "${STARSKILL_NASA_API_KEY:-}" ]; then
  .venv/bin/python -c 'from starskill.nasa import NasaApodProvider; print(NasaApodProvider.from_environment().get_feature(None).source.availability)'
else
  printf '%s\n' 'STARSKILL_NASA_API_KEY is not set; skipping APOD smoke test.'
fi
```

- [Skill 使用说明](skills/run-starskill/SKILL.md)
- [CLI 契约](skills/run-starskill/references/cli-contract.md)
- [评测协议](evaluation/README.md)
- [评测文档总览](docs/starskill-evaluation/README.md)
- [最终技术报告](docs/final-technical-report.md)
