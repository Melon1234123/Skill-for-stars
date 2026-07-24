# StarSkill 纯 Python 本机星图设计规范

**状态：** 待用户评审，未实现。
**决策日期：** 2026-07-23。
**目标：** 用现有 FastAPI、Astropy 与 Matplotlib 提供一个只监听本机回环地址、可由普通用户直接打开浏览器使用的可复现星图；核心启动不依赖 Node.js、npm、Docker、Stellarium Web Engine 或桌面 Stellarium。

## 1. 范围与非目标

### 1.1 范围

- 新增 `starskill sky-chart --open`，启动本机服务并打开 `http://127.0.0.1:8000/`。
- 页面提供地点、经度、纬度、IANA 时区、日期时间、目标名称/坐标和 24 小时时间滑块；滑块每次移动均以当前表单状态重绘。
- 默认场景在同一张静态 PNG 中绘制亮星、星座连线、月球、太阳系主要行星、水平方位地平线和目标标记。
- 用户可导出所见场景的 PNG 与同一渲染请求产生的 JSON 元数据；两者由同一个 `render_id` 和 SHA-256 关联。
- 提供显式、可选的完整星表下载命令；未下载时仍可离线使用随包亮星表。
- 所有几何计算与图像生成均在 Python 服务端完成；浏览器只承担原生 HTML 表单、范围滑块、`fetch` 和 `<img>` 显示。

### 1.2 非目标

- 不模拟 Stellarium 的 WebGL、星表深度、星云贴图、全天漫游、望远镜控制、实时气象或光害可视化。
- 不将服务绑定到 `0.0.0.0`、局域网地址或用户提供的任意 host；不添加 CORS。
- 不要求浏览器定位权限，不上传地点、时间、目标、图像或缓存内容。
- 不下载或使用 JPL/SPICE 大型星历；行星和月球使用 Astropy `solar_system_ephemeris='builtin'`。
- 不在本功能中删除或改写既有天气、NASA、MCP、观测计划能力。

## 2. 替换与迁移决策

本设计**替换** [浏览器 Stellarium 方案](../plans/2026-07-23-browser-starmap-web.md) 中的 Docker/Emscripten、Stellarium Web Engine、React、TypeScript、Vite、Vitest、Playwright 与 `web/dist` 静态站点路线。该计划不得继续实施。

现有 [live-outreach 设计](2026-07-23-live-outreach-design.md) 中关于天气、光害、NASA、建议器与 MCP 的领域约束继续有效；其中关于浏览器内嵌 Stellarium、Node/Docker 全新克隆与浏览器客户端的段落由本规范取代。两份文档冲突时，本规范对 `sky-chart`、`starskill-web`、浏览器依赖和本机启动方式优先。

批准实现时按以下顺序迁移：

1. 删除弃用的未提交 `web/` 目录、`.gitmodules` 中的 `stellarium-web-engine` 子模块记录、其 AGPL 许可/第三方通知以及 README 中引用它们的内容；仅当这些文件确为本次弃用路线的文件才删除。
2. 使 `starskill-web` 不再要求 `web/dist`，由 `src/starskill/web_api.py` 托管 Python 包内的页面与 API。
3. 以本规范定义的 `sky_chart` 领域模块、Pydantic 模型、CLI 和 FastAPI 路由取代前述浏览器计划中的前端工程。
4. 保留现有 `starskill.stellarium_bridge`、MCP `sync_stellarium` 和 `/v1/stellarium/sync` 作为已存在的可选兼容功能，但新星图页面不调用、展示或要求它们；其存在不构成 `sky-chart` 的依赖。
5. 更新 README 与 `skills/run-starskill` 的本机网页说明，删除 Node/Docker/浏览器引擎前置条件，只声明 Python 3.11+ 与 `pip install -e ".[dev]"`。

未提交的 `web/` 工件在本次设计阶段保持原样，既不构建也不删除。

## 3. 架构与本机数据流

```text
浏览器原生页面（同源 HTML/CSS/少量原生 JS）
  | POST /v1/sky-chart/render  (JSON，地点/时间/目标/星表模式)
  v
FastAPI，仅 127.0.0.1
  |-- Pydantic 校验、速率限制、单渲染并发闸门
  |-- SkyChartService
  |     |-- BundledBrightCatalog（离线必备）
  |     |-- FullCatalogCache（可选 HYG 缓存）
  |     |-- Target resolver（先本地、再既有缓存/显式网络解析）
  |     `-- Astropy AltAz + Matplotlib PNG renderer
  `-- render store（服务进程内、TTL 15 分钟、不可枚举 ID）
        |-- /v1/sky-chart/renders/{render_id}.png
        `-- /v1/sky-chart/renders/{render_id}.json
```

`SkyChartService` 在一次请求中冻结 UTC 时刻、观测者、目标解析结果、星表选择和依赖版本，先生成 PNG 字节，再计算其 SHA-256，最后生成 JSON。响应只公开随机 `render_id` 与同源导出 URL，不公开服务器绝对路径、缓存路径、环境变量或其他运行资料。

建议的实现文件边界如下：

| 文件 | 职责 |
| --- | --- |
| `src/starskill/schemas.py` | 增加星图请求、经纬度/时间/目标、层状态和导出元数据 Pydantic 模型。 |
| `src/starskill/sky_chart.py` | 坐标计算、投影、固定图层顺序、Matplotlib 渲染和 PNG/JSON 关联。 |
| `src/starskill/sky_chart_catalog.py` | 随包亮星/星座数据、HYG 缓存加载、下载、校验与降级。 |
| `src/starskill/sky_chart_targets.py` | 解析内置对象、太阳系对象和既有目标解析器的受控适配。 |
| `src/starskill/web_api.py` | 根页面、星图 API、内存 render store、loopback 生命周期；继续保留既有 `/v1` 路由。 |
| `src/starskill/cli.py` | `sky-chart` 子命令与受限的启动/下载参数。 |
| `src/starskill/data/bright_stars.json` | 随 wheel 分发的精选亮星、Bayer/通用名称、ICRS 坐标、星等。 |
| `src/starskill/data/constellation_segments.json` | 随 wheel 分发的 IAU 缩写及亮星键之间的固定连线。 |
| `src/starskill/static/sky_chart.html` | 无构建步骤的同源页面；内嵌或相邻的原生 CSS/JS，不引用 CDN。 |

### 3.1 依赖政策

运行时只使用当前 `pyproject.toml` 已声明的 Python 依赖：`fastapi`、`uvicorn`、`astropy==7.2.0`、`matplotlib==3.10.9`、`numpy==2.4.2`、`pydantic`、`tzdata` 及 Python 标准库。实现不得为核心星图新增 Python 包；测试只使用既有 `pytest` 开发可选依赖。不得添加 `package.json`、锁文件、Node、npm、Docker、Docker Desktop、Make、WebAssembly、CDN、JavaScript 框架或远程字体。浏览器端少量原生 JavaScript 是随 Python 包分发的静态文本，不构成 Node 或独立前端运行时。

## 4. CLI、HTTP 与浏览器行为

### 4.1 CLI

```text
starskill sky-chart --open
starskill sky-chart --port 8000
starskill sky-chart --download-catalog
starskill sky-chart --download-catalog --catalog-cache-dir cache/sky-chart
```

- `--open`：服务完成 loopback bind 且 `/healthz` 返回 200 后，调用 Python `webbrowser.open` 打开根页面一次；浏览器启动失败只写明 URL，不终止已运行服务。
- `--port`：整数 `1024..65535`，默认 `8000`；不提供 `--host` 参数，代码固定 `127.0.0.1`。监听失败以非零退出，并说明端口不可用。
- `--download-catalog`：不启动 Web 服务。下载、校验并原子写入完整星表缓存，成功输出 JSON 摘要；失败不覆盖旧的有效缓存，非零退出。
- 未指定 `--download-catalog` 时，`sky-chart` 运行服务；未指定 `--open` 时在终端输出精确本机 URL，供用户手动打开。

### 4.2 HTTP 合约

现有 `/healthz` 和既有 `/v1` 路由保持。新增路由全部同源且不启用 API 文档：

| 方法与路径 | 请求/响应 | 行为 |
| --- | --- | --- |
| `GET /` | `text/html; charset=utf-8` | 返回静态本机页面，禁止缓存。 |
| `POST /v1/sky-chart/render` | `SkyChartRequest` -> `SkyChartRenderResponse` | 校验、渲染、保存 15 分钟，并返回 `render_id`、PNG/JSON URL、层状态与警告。 |
| `GET /v1/sky-chart/renders/{id}.png` | `image/png` | 下载或 `<img>` 显示 PNG；`Content-Disposition` 文件名由 `render_id` 派生。 |
| `GET /v1/sky-chart/renders/{id}.json` | `application/json` | 下载准确对应 PNG 的可复现元数据；`Content-Disposition: attachment`。 |

`render_id` 使用 `secrets.token_urlsafe(24)`；仅接受 URL-safe 字符串且查不到、过期或格式非法均返回同一 `404`，避免枚举内部状态。每个客户端每分钟最多 30 次 render；服务同时只执行一个 Matplotlib 渲染，其他请求最多等待 10 秒，超时返回 `503 {"detail":"Renderer busy; retry shortly"}`。沿用既有 1 MiB 请求体上限，星图请求额外限制为 16 KiB。

### 4.3 浏览器页面

页面首屏由左侧 PNG 星图和右侧紧凑表单组成，均为固定稳定尺寸；星图在结果返回前保留上一次成功图，不以空白替换。表单字段为：

- 地点名称、经度、纬度、IANA 时区；
- 本地日期时间；
- 从所选时刻前 12 小时到后 12 小时的范围滑块，步长 15 分钟；
- 目标文本和“按名称”/“RA-Dec”二选一模式；
- 星表模式 `auto`、`bundled`、`full`；
- “更新星图”“导出 PNG”“导出 JSON”命令。

页面首次加载的默认值为北京市（`116.4074`、`39.9042`、`Asia/Shanghai`）、服务端取得且在 `Asia/Shanghai` 中表示的当前分钟、按名称目标 `M42`、星表模式 `auto`。滑块以首个时刻为中心；用户手工更改日期时间后立即重置其 24 小时窗口。`M42` 无法离线解析时，页面仍显示完整默认星空并在目标栏说明“目标未解析，未绘制标记”，不伪造目标位置。

`auto` 仅在存在完整且校验通过的本地缓存时选择 `full`，否则选择 `bundled`；`full` 在缓存不存在时不访问网络，返回 422 并提示用户执行 `starskill sky-chart --download-catalog`。页面不会因滑块事件直接高频请求：原生 JS 在连续输入后 debounce 250 ms，上一请求用 `AbortController` 取消，但服务端仍按上节限制资源。

## 5. 输入校验与默认值

`SkyChartRequest` 使用 `extra='forbid'`，并固定如下字段与边界：

| 字段 | 类型与约束 | 默认 |
| --- | --- | --- |
| `observer.location_name` | 去首尾空白后 `1..80` Unicode 字符 | `北京` |
| `observer.longitude` | 浮点，`-180 <= value <= 180` | `116.4074` |
| `observer.latitude` | 浮点，`-90 <= value <= 90` | `39.9042` |
| `observer.timezone` | 可由 `zoneinfo.ZoneInfo` 加载的 IANA 名称 | `Asia/Shanghai` |
| `timestamp_local` | 含 offset 的 ISO 8601；offset 必须等于时区在该时刻的实际 offset | 启动时冻结的当地当前分钟 |
| `target.mode` | `name` 或 `coordinates` | `name` |
| `target.name` | `name` 模式必填，`1..120` 字符；禁止控制字符 | `M42` |
| `target.ra_deg` | `coordinates` 模式必填，`0 <= value < 360` | 无 |
| `target.dec_deg` | `coordinates` 模式必填，`-90 <= value <= 90` | 无 |
| `catalog_mode` | `auto`、`bundled`、`full` | `auto` |
| `width_px`、`height_px` | 仅服务端允许的 `1200 x 900`，客户端不传入 | 固定 |

缺少、越界、时区不一致或目标模式字段不完整返回 422 `{"detail":"Invalid sky-chart request"}`，不回显原请求或内部异常。目标名解析只允许内置名、太阳系固定名或既有 SIMBAD 解析器；不接受 URL、文件路径、脚本、任意网络地址或 shell 语法。

## 6. 确定性计算、投影与图层

所有时间先转 `astropy.time.Time` 的 UTC，`EarthLocation` 由用户经纬度构建，水平坐标系固定为 `AltAz(obstime=..., location=..., pressure=0*u.hPa)`。在每次渲染上下文中设置：

```python
iers.conf.auto_download = False
solar_system_ephemeris.set("builtin")
matplotlib.rcParams.update({"figure.dpi": 100, "savefig.dpi": 100, "font.family": "DejaVu Sans"})
```

绘图采用方位角等距天顶投影：`r=(90-altitude_deg)/90`，`x=r*sin(azimuth_rad)`，`y=r*cos(azimuth_rad)`；仅 `altitude_deg >= 0` 的对象可见。图像尺寸固定 1200x900、100 DPI、黑色无透明背景、固定色值、固定随机种子 `0`，关闭自动布局和依赖系统时间的文字。渲染顺序不可改变：

1. 深色背景与地平线外遮罩；
2. 地平线圆、方位 N/E/S/W 与高度圈（0、30、60、90 度）；
3. 星座连线；
4. 星点，按星等从暗到亮绘制；
5. 月球；
6. 水星、金星、火星、木星、土星、天王星、海王星及其中文/英文固定标签；
7. 已解析目标的黄色十字、同心圆和标签；
8. 页脚事实标签：地点、时区、本地时刻、UTC、星表模式、星表状态和计算模型。

太阳低于地平线仍按真实星图绘制；太阳本身不列入默认“主要行星”，以免把昼间视图误导为夜空。行星/目标低于地平线时不画其标记，JSON 仍记录 `visible=false` 与高度角。月球以当前相位照明比例填充，其盘面朝向不承诺物理月海纹理。

给定完全相同的 `SkyChartRequest`、星表内容 SHA-256、Python/Astropy/Matplotlib 版本、时区数据库版本和字体文件，PNG 字节必须相同。跨操作系统字体渲染的字节一致性不作为承诺；验收比较元数据、图层对象和感知图像哈希，而不是跨平台 PNG 字节。

## 7. 星表缓存、来源与离线降级

### 7.1 随包数据

wheel 内固定分发 `bright_stars.json`（至少肉眼亮星与其 ICRS J2000 坐标、视星等、名称）和 `constellation_segments.json`（仅在两个端点均存在时绘制）。它们的 `dataset_id`、版本、许可证、来源 URL 和文件 SHA-256 均写入 JSON 元数据。该数据是零网络默认路径。

### 7.2 可选完整星表

完整星表采用 HYG Database v4.1 的固定发布文件；缓存逻辑把下载地址、数据集版本、许可文本标识、HTTP `ETag`/`Last-Modified`（若提供）、访问时间、压缩文件 SHA-256、解压后 CSV SHA-256 和行数记录到 `cache/sky-chart/hyg-v4.1/manifest.json`。下载流最大 128 MiB，使用临时文件、校验 CSV 表头和行数大于 100000 后才以原子 rename 发布。渲染只读取已发布且其 manifest/hash 都一致的缓存。

下载不能通过页面触发；仅 `starskill sky-chart --download-catalog` 可以发起，并且只访问代码固定的 HTTPS 来源。网络不可用、HTTP 状态异常、体积超限、CSV 列缺失、哈希不一致或解析失败时：

- 有旧有效缓存：保留它，退出失败并明确下载未更新；
- 无有效缓存：不创建部分缓存；
- Web 的 `auto`：使用 `bundled` 并把 `catalog_status="degraded"` 写入 PNG 页脚、API 和 JSON；
- Web 的 `full`：返回 422，不降级为完整星表的假象。

缓存不承诺自行刷新；只有用户再次显式运行下载命令才检查上游。完整星表只提高恒星密度，不改变天体位置计算模型或内置星座线。

## 8. PNG 与 JSON 导出契约

导出的 PNG 文件名为 `starskill-sky-chart-{render_id}.png`，JSON 为 `starskill-sky-chart-{render_id}.json`。JSON 的顶层 schema 固定为：

```json
{
  "schema_version": "1.0",
  "render_id": "opaque-url-safe-id",
  "created_at_utc": "2026-07-23T12:00:00Z",
  "request": {
    "observer": {"location_name": "北京", "longitude": 116.4074, "latitude": 39.9042, "timezone": "Asia/Shanghai"},
    "timestamp_local": "2026-07-23T20:00:00+08:00",
    "timestamp_utc": "2026-07-23T12:00:00Z",
    "target": {"mode": "name", "input": "M42", "resolved": null},
    "catalog_mode_requested": "auto",
    "catalog_mode_used": "bundled"
  },
  "render": {"projection": "azimuthal_equidistant_zenith", "width_px": 1200, "height_px": 900, "layer_order": ["background", "horizon_grid", "constellations", "stars", "moon", "planets", "target", "footer"], "png_sha256": "64-lowercase-hex"},
  "objects": {"moon": {}, "planets": [], "target": null, "stars_drawn": 0, "constellation_segments_drawn": 0},
  "catalog": {"dataset_id": "bundled-bright-stars", "version": "...", "source_url": "...", "license": "...", "sha256": "64-lowercase-hex", "status": "available"},
  "calculation": {"time_scale": "UTC", "horizontal_frame": "AltAz", "atmospheric_refraction": false, "solar_system_ephemeris": "builtin", "iers_auto_download": false},
  "dependencies": {"python": "...", "astropy": "7.2.0", "matplotlib": "3.10.9", "tzdata": "..."},
  "warnings": []
}
```

对象数组中的每一个月球、行星和目标项必须包含 ICRS（适用时）和 AltAz 数值、单位为度、`visible`、`drawn` 和显示标签；`objects.target` 无法解析时为 `null`，并在 `warnings` 写入机器可读代码 `target_unresolved`。所有坐标数值至少保留 6 位小数，时间使用 ISO 8601 和明确 offset。JSON 不包含网络凭据、服务器路径、客户端 IP、堆栈或原始 HTTP 头。

## 9. 生命周期、错误与安全边界

- 服务只由 `starskill sky-chart` 或 `starskill-web` 启动，均把 Uvicorn `host` 硬编码为 `127.0.0.1`。`starskill-web` 采用同一应用和端口策略，不能回退到当前的 `web/dist` 检查。
- 收到 SIGINT/SIGTERM 后停止接收新请求，等待正在执行的单个渲染至多 10 秒，清除内存 render store，退出码 0；端口冲突、未处理启动错误或目录不可写则非零退出。
- render store 只存内存且最大 20 份结果或 50 MiB，按最早到期优先逐出；不在工作目录留下临时图像。命令行下载缓存是唯一持久星图相关缓存。
- 仅使用 `pathlib` 构造服务器拥有的缓存路径，不从 HTTP 接受文件名、路径、上游 URL、字体路径或 Matplotlib 配置。HTTP 错误统一为简短稳定消息，详细异常仅进入本机不含敏感字段的日志。
- 继续执行既有请求体/速率保护；新增渲染并发和缓存上限应覆盖 Matplotlib CPU、内存与文件描述符风险。禁止 API 返回目录列表或 cache 命中路径。
- 外部网络仅用于用户明确的星表下载及既有目标解析。目标解析网络失败不会阻止恒星、星座、月球、行星和地平线渲染。

## 10. 测试与全新克隆验收

测试不得访问真实网络、系统浏览器、Docker、Node 或桌面 Stellarium。使用固定时刻、固定 Paris/Beijing 观测者与本地临时缓存夹具。

| 层级 | 必须验证 |
| --- | --- |
| schemas | 坐标边界、IANA 时区、offset 一致性、目标二选一、`catalog_mode=full` 无缓存的 422 契约。 |
| renderer | 固定请求的层顺序、对象可见性、坐标单位、PNG 非空、JSON `png_sha256` 与实际 PNG 相同；不要求跨 OS 字节相同。 |
| catalog | bundled 离线可用；有效 HYG fixture 加载；下载超限/坏哈希/坏 CSV 原子失败；旧有效缓存保留；`auto` 与 `full` 的不同降级。 |
| CLI | `sky-chart --help`、`--port` 边界、`--download-catalog` 不启动 Uvicorn、`--open` 只在 health 成功后请求浏览器。 |
| FastAPI | 固定 `127.0.0.1` 启动配置、`/healthz`、有效 render 到两种导出、无效/过期 ID 的同一 404、16 KiB 上限、30 RPM 限流、繁忙 503。 |
| 页面 | 用 `TestClient` 检查根页面不包含 npm、Docker、CDN、Stellarium 或 `http://` 外域；检查表单标签、range、两种导出链接和失败消息。 |
| 回归 | `pytest -q` 继续覆盖当前 `web_api`、MCP、`stellarium_bridge` 和既有观测工作流。 |

全新克隆验收命令固定为：

```bash
clone_dir=$(mktemp -d)
git clone https://github.com/Melon1234123/Skill-for-stars.git "$clone_dir"
cd "$clone_dir"
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/starskill sky-chart --port 8000
```

在第二终端执行 `curl -fsS http://127.0.0.1:8000/healthz`，期望 `{"status":"ok"}`；打开根页面，使用默认值成功得到非空 PNG 和相同 `render_id` 的 JSON，下载二者并核对 `png_sha256`。随后关闭服务，并运行 `.venv/bin/starskill sky-chart --download-catalog` 仅在网络可用时作为单独、非 CI 的可选验证。整个核心验收不执行 `node`、`npm`、`docker`、`make` 或任何 Stellarium 程序。

## 11. 分阶段落地步骤

1. 添加星图 Pydantic 模型、随包亮星/星座数据和纯函数渲染测试，先用固定请求验证 PNG/JSON 对应关系。
2. 添加完整星表缓存/下载器及其离线 fixture 测试，确保 `bundled`、`auto`、`full` 的行为彼此可区分。
3. 在 CLI 增加 `sky-chart` 子命令、受限端口、显式下载和仅 health 成功后的 `--open`；完成 CLI 失败路径测试。
4. 将 FastAPI 的根页面和星图路由接入当前 `create_web_app`，以无构建静态资源取代对 `web/dist` 的要求；完成 API、限流、TTL 与导出测试。
5. 删除已弃用的未提交 `web/`、子模块和其许可证/通知引用，更新 README、`skills/run-starskill` 和旧浏览器计划的状态为“已由本规范取代”；执行全量 Python 测试与全新克隆验收。

每一步必须在同一个提交中包含实现、相应测试和文档修改；不允许留下 Node/Docker 兼容分支、空页面或“稍后构建”的运行时路径。

## 12. 已识别兼容性风险与评审假设

1. **已证实的当前风险：** `src/starskill/web_api.py` 目前在 `web/dist` 缺失时直接抛出 `FileNotFoundError`，而仓库现有 `web/` 只有弃用路线的 vendor/Makefile 工件，没有可用 `dist`。因此现有 `starskill-web` 不能满足新方向，必须改为服务包内页面。
2. **已证实的文档冲突：** README 同时声称当前没有 `web/` 工程，却在工作树中已有未提交的 `.gitmodules` 与 `web/` 工件；迁移实现应以 Git 跟踪状态和本规范为准，不可把它们当作已发布能力。
3. **已证实的契约风险：** 现有 MCP 与测试直接使用 `StellariumBridge`/`sync_stellarium`。删除该桥接会造成不必要的 API 回归，故本规范将其保留但与纯 Python 星图解耦。
4. **待用户确认的产品假设：** 默认地点采用北京、默认目标采用 M42；这是便于中国教学演示的产品默认值，并非从用户位置自动推断。若目标用户群不同，应在实现开始前替换这一组默认值。
5. **待实现前验证的来源风险：** HYG v4.1 的固定发布 URL、分发许可文本和文件 SHA-256 尚未在本次仅设计审查中联网核验。实现必须在写入固定下载源前核对上游发布页与许可，并把实际已验证的 URL/哈希写入代码、测试夹具和 README；在此之前完整星表下载功能不得声称可用。
