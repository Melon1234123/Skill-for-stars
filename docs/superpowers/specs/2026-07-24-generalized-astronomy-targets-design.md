# StarSkill 通用天体关系与可信图像检索设计

**状态：架构已确认，待用户审阅规格**
**日期：2026-07-24**

## 1. 已确认的决定

StarSkill 的固定案例能力将泛化为通用天文目标能力，但不会把未验证的
网页内容、轨道模型或物理结论伪装成事实。

1. `relationship` 支持任意两种目标引用的组合：太阳系动态天体、SIMBAD
   名称目标或用户提供的 ICRS 坐标。
2. 第一阶段的关系只表示给定观测者、时间和地点下的视位置、可见性与天空
   角距离。它不报告物理三维距离、引力关系、会合、冲日或合相事件。
3. 用户可以直接提供 ICRS 赤经/赤纬；产物必须标明此坐标未经目录解析。
4. `fetch-image` 可发现公开网页和 API 候选，但只自动下载满足高可信准入
   规则的科学档案候选。模型只能排序和解释候选，不能自行授予下载信任。
5. 旧的月亮-木星关系和 M51/SDSS 接口保留兼容包装器；新调用方使用通用
   关系和图像检索合同。

本设计中“任意”表示任意两个受支持 `TargetRef` 的组合，以及任意坐标所对应
的图像检索；它不表示无验证地执行任意网站内容，也不表示所有小天体都已有
可信动态轨道星历。

## 2. 目标与非目标

### 目标

- 让 CLI、MCP、完整观测流程和本地星图共享一个明确的目标引用模型。
- 正确区分会随时间变化的太阳系天体与固定 ICRS 坐标目标。
- 为任意两目标输出可复算的视位置和角距离时间序列，并保留数据来源、
  时间尺度、星历策略与人工复核边界。
- 用可审计的候选发现、可信度排序、确定性下载准入和内容验证替代当前
  M51/SDSS 专用图像流程。
- 保留现有月亮-木星、M42 和 M51 示例，以避免破坏已有课程材料和评测证据。

### 非目标

- 不从两个 SIMBAD 位置推断真实三维距离。距离、视差和自行并不总是可用，
  且其不确定度不能省略。
- 不把静态 SIMBAD 坐标当作彗星、小行星或行星的动态轨道。
- 不让模型执行网页 JavaScript、跟随任意下载链接、读取本机文件或访问私网。
- 不把模型评分、图片可见性或网页声明当作许可证、科学真实性或观测安全的
  最终证明。
- 第一阶段不实现物理距离、掩星、合相、冲日或最近角距事件求根；这些需要
  单独的科学定义和误差策略。

## 3. 方案选择

采用“开放发现，高可信下载闸门”方案。

```text
TargetRef -> target resolution -> astrometric computation -> relationship/run/chart

Image request -> public candidate discovery -> optional model ranking
              -> deterministic trust gate -> bounded download -> validation
              -> cache + provenance artifacts
```

纯模型直接下载任意网页被拒绝：它无法提供稳定的来源保证，容易受到网页提示
注入、重定向和伪元数据影响。仅使用 IVOA/SIA 的方案也不采用，因为会排除部分
重要公开档案。开放发现可以覆盖更广来源，但自动下载只能通过确定性闸门。

## 4. 通用目标模型

新增一个版本化、判别联合的 `TargetRef`。所有新接口使用它；旧的字符串目标
或 `targets: ["moon", "jupiter"]` 只作为输入兼容层，并在解析后转换为
`TargetRef`。

```json
{
  "kind": "solar_system",
  "body": "mars"
}
```

```json
{
  "kind": "simbad",
  "name": "M 31"
}
```

```json
{
  "kind": "coordinates",
  "label": "user target",
  "ra_deg": 10.684708,
  "dec_deg": 41.268750
}
```

### 4.1 解析规则

| `kind` | 解析方法 | 产物来源标记 |
| --- | --- | --- |
| `solar_system` | Astropy `get_body`，在每个采样时刻计算 | `astropy_builtin_ephemeris` |
| `simbad` | 安全规范化名称，SIMBAD 查询或已验证缓存 | `simbad` 或 `simbad_cache` |
| `coordinates` | 校验 ICRS RA `[0, 360)` 与 Dec `[-90, 90]`，不访问网络 | `user_coordinates` |

太阳系目标名使用打包的规范名称表，并与当前本地 Astropy `builtin` 星历的实际
支持范围一起测试。第一阶段包含太阳、月亮和水星至海王星。Astropy `builtin`
不提供冥王星的位置；冥王星、彗星、小行星和其它小天体在引入带版本、来源和离线
策略的受控星历提供方前，以结构化 `unsupported_solar_system_body` 失败，不静默
退化为 SIMBAD 静态坐标。

`simbad` 目标只保存目录返回的 ICRS 赤经、赤纬、标准名称、天体类型、别名、
来源 URL、访问时间与缓存状态。`coordinates` 目标保存用户标签和精确输入值。
目标解析结果必须说明它是 `dynamic` 还是 `fixed_icrs`。

### 4.2 复用与迁移

`SkyChartTargetResolver` 已实现太阳系名称、SIMBAD 名称和坐标三类输入。其目标
分类逻辑迁移为无 UI 依赖的核心解析层；星图改为调用该核心层。旧
`ObservationTask.target: str` 继续接受字符串，并规范化为 `{"kind":"simbad"}`。
旧月亮-木星任务继续可解析、使用通用核心计算，并经输出适配器维持既有 schema
v1；只有新通用任务写入 schema v2。

## 5. 通用关系计算

### 5.1 输入与输出

新的 `AstronomicalRelationshipTask` 使用有序的 `primary` 和 `secondary`
`TargetRef`，以及现有 `observer`、`time_range` 和 `interval_minutes`。

每个采样输出包含：

- 本地和 UTC 时间戳；
- 两个目标的标签、目标种类、来源、可见性、高度角和方位角；
- `angular_separation_deg`，定义为同一时刻两条视线的球面夹角；
- 计算设置：Astropy 版本、UTC、`AltAz`、无大气折射、IERS 自动下载关闭和
  使用的太阳系星历；
- 每个非网络或网络目标的实际来源和缓存状态。

新通用任务的 CSV 使用 `primary_*` 与 `secondary_*`，JSON 使用
`schema_version: "2.0"`。旧月亮-木星输入仍写入既有 `moon_*`、`jupiter_*`
列和 schema v1，由适配器从通用核心结果转换。两种格式都保留原有文件名
`relationship.csv` 和 `relationship.json`，因此旧读者不被静默破坏。

### 5.2 计算过程

1. 以观测者时区生成包含端点的时间网格，并转换为 UTC。
2. 由经纬度创建 `EarthLocation`，创建压力为零的 `AltAz` 框架。
3. 对 `solar_system` 目标，在每个 UTC 时刻调用 Astropy `get_body`，再转换至
   该 `AltAz` 框架。
4. 对 `simbad` 与 `coordinates` 目标，使用 ICRS `SkyCoord`，再转换至同一
   `AltAz` 框架。
5. 在两个目标的同一坐标框架上计算 `separation`。这是视线角距离，绝不称为
   空间距离。

因此支持太阳系-太阳系、太阳系-SIMBAD、太阳系-坐标、SIMBAD-SIMBAD、
SIMBAD-坐标和坐标-坐标的全部有序组合。

### 5.3 CLI、MCP 和兼容接口

- `starskill relationship` 接受新任务格式；旧的精确月亮-木星输入先转换为
  通用任务。
- MCP 新增 `calculate_astronomical_relationship`，接受同一通用任务并继续通过
  服务拥有的运行目录公开资源。
- 旧 `calculate_moon_jupiter_relationship` 保留为包装器，调用通用函数后转换为
  既有响应 schema，不创建第二套计算逻辑。
- `run`、`ephemeris` 和 `plan` 接收 `TargetRef`，使太阳系目标走动态星历，
  SIMBAD 和坐标目标走固定 ICRS 链路。

## 6. 可信图像检索

### 6.1 通用请求

新的 `AstronomyImageSearchRequest` 包含 `target: TargetRef`、视场范围、期望
波段、最大宽高、允许格式、超时、最大字节数和 `provider_mode`。`provider_mode`
默认为 `auto_trusted`；用户可指定某个已注册提供方以确保教学演示完全可重复。

检索前，所有目标都转换为可查询坐标。太阳系目标必须在请求指定的观测时刻计算
坐标；SIMBAD 和用户坐标使用解析后的 ICRS 坐标。M51/SDSS 请求转换为该通用请求
的兼容包装器。

### 6.2 提供方与候选发现

提供方注册表由独立适配器构成。首批适配器为 SDSS DR18 Image Cutout、MAST
Observations、ESA Sky 和 Pan-STARRS Public Image 服务。每个适配器声明：

- 机构所有者、允许的 HTTPS 主机、固定 API 端点和重定向主机；
- 可查询坐标、波段、视场和格式；
- 许可证或使用政策 URL；
- 最大响应大小、允许 MIME 类型和解码器；
- 如何从其响应构造可复算的来源 URL 与查询参数。

开放发现适配器可以从公开网页/API 收集候选元数据，但不下载候选图片。页面正文
和描述字段均被视为不可信数据，不能作为执行指令。

可选 `ModelRanker` 仅接收规范化候选元数据，并以严格 JSON 输出候选 ID、
`0.0..1.0` 可信度、相关性和理由。模型名称、版本、提示词哈希、评分和原始结构化
响应写入 `image_search.json`。未配置模型时，系统仍按确定性提供方优先级工作。

### 6.3 自动下载准入

`auto_trusted` 仅下载同时满足下列条件的候选：

1. 候选来自注册的 Tier-1 科学档案适配器，且最终主机与该适配器允许主机匹配；
2. URL 和每次重定向均为 HTTPS，重定向不超过 3 次，目标不是回环、私有、链路
   本地或保留地址；
3. 提供方声明了来源和许可证/使用政策；
4. 模型启用时，可信度不低于 `0.85`；未启用模型时，候选仍需满足其他全部规则；
5. 响应在读取前后的字节上限检查均通过，MIME、实际解码格式、像素尺寸和
   请求参数一致。

未知域名、网页托管图片、无许可证线索、模型低分或不匹配重定向一律写入候选
报告为 `requires_human_review`，不自动下载。用户可以显式指定已注册提供方，
但不能通过输入 URL 绕过注册表。

第一阶段接受 JPEG、PNG 和 FITS；HTML、SVG、PDF 和含脚本的文档不是图像数据。
处理产物单独记录转换、裁剪、拉伸和标注步骤，不把展示图误称为原始科学数据。

### 6.4 产物、缓存和错误

每次图像检索创建：

- `image_search.json`：规范化请求、所有候选、提供方、评分、拒绝原因和选择结果；
- `image_metadata.json`：最终来源、许可证、查询参数、访问时间、重定向链、
  Content-Type、字节数、像素尺寸、SHA-256、缓存状态和处理步骤；
- 原始数据文件与展示 PNG；
- `run.json` 中的全部路径和 SHA-256。

缓存键含提供方 ID、规范化请求、最终来源 URL 和内容哈希。失败明确区分：无候选、
候选未达信任阈值、未注册提供方、网络/HTTP 错误、重定向拒绝、大小超限、MIME/
解码失败和许可证信息缺失。任何失败都不得伪造图像或回退到不相关的历史缓存。

## 7. 传输层与安全边界

CLI、MCP 和本地 Web API 复用同一领域函数和 Pydantic 模型。MCP 继续仅公开
`starskill://runs/{run_id}/{resource}` 白名单资源；客户端不能提供输出目录、缓存
目录、本机路径、任意 URL 或模型凭据。

模型凭据只可来自显式环境配置，永不写入请求、缓存、运行清单、日志或资源内容。
模型不可调用 shell、浏览器、下载器或本机文件系统。下载器只消耗已通过信任闸门的
候选 URL，并使用受限 HTTP 客户端。

## 8. 测试与验收

### 单元与契约测试

1. 对三种 `TargetRef` 覆盖全部九种有序目标组合，固定时间、地点和离线 IERS 数据。
2. 验证太阳系动态位置随时间改变；SIMBAD/坐标走固定 ICRS 路径；SIMBAD-SIMBAD
   输出不访问太阳系动态计算。
3. 验证旧月亮-木星输入与通用任务的计算结果在对应字段上相同。
4. 验证无效身体名、非法坐标、SIMBAD 不可用、缓存损坏、时区错误和空时间窗的
   结构化失败行为。
5. 用 fake provider、fake discoverer 和 fake ranker 验证每个下载闸门条件、
   评分阈值、重定向拒绝、私网拒绝、许可证缺失、大小限制、JPEG/PNG/FITS 解码、
   缓存哈希不匹配与无候选情况。默认测试不得访问真实网络或模型。
6. 验证 MCP 工具发现、输入验证、通用运行资源和旧包装器一致调用核心函数。

### 回归与端到端验收

1. 保留并运行现有 M42、月亮-木星和 M51 固定案例；它们必须在兼容入口保持可用。
2. 新增固定夹具：火星-土星、火星-M31、M31-用户坐标和用户坐标-用户坐标。
3. 在 script-owned acceptance 中保存新任务、实际 argv、退出码、stdout/stderr、
   每个产物哈希和回放结果；外部 Worker/Reviewer 证据仍与工程验收分离。
4. 将真实档案与模型调用列为显式 opt-in live smoke test。它们生成独立产物，
   不得成为离线 CI 的唯一通过条件。
5. 从空目录重新克隆、安装并运行完整测试、通用关系案例、MCP stdio 发现和一个
   受控的高可信图像下载验收。

## 9. 文档与发布

README、CLI 合同、`run-starskill` Skill、MCP 文档、示例任务和评测说明同步改为
通用目标术语。文档明确区分：视位置角距离、目录坐标、动态太阳系星历、模型候选
评分、确定性下载准入和人工复核。实现完成后，全局安装的 `run-starskill` 副本必须
从远程 `main` 重新同步，并在全新克隆中重新验收。
