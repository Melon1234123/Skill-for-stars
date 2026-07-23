# StarSkill 实时科普与浏览器星图设计

**状态：已确认，待实现**  
**日期：2026-07-23**

## 1. 目标与范围

在现有可追溯天文观测工作流和本地 `stdio` MCP 服务之上，增加面向
课堂与科普活动的实时辅助能力：

- 浏览器内嵌的交互星图；
- 与本机 Stellarium RemoteControl 的可选桥接；
- 短期天气预报与静态光害指标；
- NASA Open APIs 的可溯源科普素材；
- 面向智能体的“今晚观测建议”MCP 工具。

本功能不宣称实际云量、透明度、地平线遮挡、设备适配或现场安全已经
核验。推荐结果必须把几何计算、外部预报、静态环境数据和人工复核项分开。

## 2. 许可证与分发

浏览器星图采用 Stellarium Web Engine。该引擎仓库包含 AGPL-3.0
许可证，因此实现阶段必须：

1. 在仓库根目录加入 AGPL-3.0 许可证文本；
2. 在 Web 应用的关于页面、README 和第三方归属文件中说明
   Stellarium Web Engine 的来源与许可证；
3. 将与该引擎组合并分发的 Web 应用源代码以符合 AGPL-3.0 的方式提供；
4. 不将 Stellarium Web Engine 的许可证误述为 StarSkill 既有依赖的许可证。

Stellarium 桌面桥接只访问用户明确开启的 RemoteControl HTTP 服务，默认
仅允许回环地址。它是辅助同步，不是浏览器星图能够工作的前置条件。

## 3. 架构

```text
Browser Web App
  |- Stellarium Web Engine (WebGL star map)
  |- Recommendation panel
  `- HTTP API client
          |
          v
Loopback StarSkill Web App
  |- Astronomy domain functions (existing Astropy workflow)
  |- Weather provider adapter
  |- Light-pollution provider adapter
  |- NASA content provider adapter
  `- Optional localhost Stellarium bridge
          |
          +--> versioned run artifacts and caches

Local stdio MCP server
  `- same domain functions and provider adapters
```

Web App 和 MCP 服务共享领域模型、来源记录、缓存策略和建议生成器；它们只在
传输层上不同。`starskill-web` 同时托管构建后的浏览器文件和同源 `/v1` API，且
硬性绑定 `127.0.0.1`；现有 `starskill-mcp` 保持 `stdio`。二者都不得作为公网
服务运行。

## 4. 浏览器体验

页面以星图为主体，使用经纬度、时区和当前选择的时间驱动星空。观测建议面板
显示目标高度、方位、太阳高度、月相/月距、预报天气、静态环境亮度和推荐窗口。
用户可搜索已支持的目标、切换时间、选择地点、请求今晚建议，以及选择是否同步
至本机 Stellarium。

每个外部信息旁显示来源、数据时间和状态。数据过期、提供方失败或未配置凭据时，
面板显示不可用或已降级，不以前一次成功结果冒充当前数据。

## 5. 数据契约

### 5.1 几何条件

复用现有 Astropy 计算的目标高度/方位、太阳高度、月亮高度、月面照明比例和
目标月亮角距。它们是确定性计算事实，并继续生成可复查的时间序列。

### 5.2 天气预报

首个提供方为 Open-Meteo 的小时预报接口。适配器输入为观测点和时间范围，输出
必须包含每个样本的云量、降水、风、能见度（若上游提供）、提供方时间戳、模型或
接口元数据、访问时间和缓存状态。推荐器只使用实际返回的字段；缺失字段不得以
默认“晴朗”替代。

天气结果描述为“预报条件”，并以原始时间粒度呈现。客户端不得把小时预报解释为
分钟级实测，或据此给出安全保证。

### 5.3 光害

光害由 `LightPollutionProvider` 抽象，首个实现读取版本化的 NASA Black
Marble/VIIRS 夜间辐亮度快照。每项结果必须包含数据集标识、版本、采样期、空间
分辨率、像元/插值方法、单位或无量纲等级、来源 URL、访问时间和缓存状态。

该值是静态或历史环境亮度指标，不是实时光害传感器读数，也不得自动等同于
Bortle 等级。无法取得有效数据时，推荐器保留几何与天气结果，并将光害状态标为
`unavailable`。

### 5.4 NASA 科普素材

首个实现调用 NASA APOD。返回值保存标题、日期、媒体类型、原始媒体 URL、解释
文本、版权字段（若有）、API 访问时间和缓存状态。NASA 素材仅服务讲解展示，不
参与观测条件评分或安全判断。API Key 通过环境变量提供，禁止写入源代码、运行
清单或日志。

### 5.5 Stellarium 桥接

`StellariumBridge` 调用用户本机 RemoteControl 的 HTTP API，支持健康检查、
读取状态、设置地点/时间和按名称选择目标。默认基址仅为 `http://127.0.0.1:8090`；
非回环地址须通过显式配置启用。桥接失败只返回结构化不可用状态，绝不影响几何
计算和浏览器星图。

## 6. MCP 与 Web API

新增的领域操作为：

| 操作 | 用途 | 主要输出 |
| --- | --- | --- |
| `get_observing_conditions` | 获取天气和光害证据 | 结构化样本、来源、状态、缓存信息 |
| `recommend_tonight` | 合并几何和外部条件 | 分时段建议、逐项理由、人工复核项、运行资源 |
| `get_nasa_feature` | 获取当日或指定日期 APOD | 科普素材和完整来源信息 |
| `sync_stellarium` | 同步到可选本机 Stellarium | 桥接状态和实际执行的操作 |

MCP 输出和 Web API 响应都必须使用同一个版本化结果模型。每次建议运行创建独立
目录，并新增只读资源名称，例如 `conditions`、`recommendation`、
`nasa-feature` 和 `stellarium-sync`。资源白名单继续防止任意文件读取。

`recommend_tonight` 的结果包含：

- `geometry`: 当前星历和几何候选窗口；
- `weather_forecast`: 提供方原始证据及其状态；
- `light_pollution`: 静态数据快照及其状态；
- `recommendations`: 推荐、谨慎或不推荐的窗口和明确理由；
- `human_review`: 现场天气、地平线、设备和安全检查项；
- `provenance`: 所有外部来源、参数、访问时间、缓存和降级原因。

只有几何规则和已声明的保守阈值可以决定推荐等级；外部提供方缺失时不得提高
等级。无论等级为何，`human_review` 始终必填。

## 7. 可靠性与安全

每个外部适配器都使用显式超时、响应大小上限、内容类型/JSON Schema 校验、
确定性的缓存键和受控重试。失败分类至少区分未配置、超时、HTTP/网络错误、格式
错误、无数据和陈旧缓存。运行产物记录实际使用的是新鲜数据、已验证缓存还是降级
状态。

Web App 必须硬性绑定回环地址、拒绝非同源跨域访问、限制请求体和请求速率，并写入
不包含密钥的结构化日志。浏览器只能调用同源 Web API，不能读取服务器缓存目录或向
Stellarium 桥接传入任意 URL。README 必须给出从克隆、安装依赖、构建星图、启动
本地服务到配置可选 NASA Key/光害快照的完整步骤。

## 8. 测试与验收

1. 为每个提供方协议建立 fake backend，覆盖成功、缓存命中、超时、无效响应、
   大小超限、缺少 API Key 和陈旧缓存；测试不得访问真实网络。
2. 为建议器建立固定星历、天气和光害夹具，验证理由、状态传播、时间对齐和
   `human_review` 永远存在。
3. 为 Stellarium 桥接建立本地 HTTP 假服务，验证只接受默认回环地址、请求参数
   正确且失败不会中断推荐。
4. 为 MCP 新工具验证工具发现、输入校验、运行资源白名单和结构化降级输出。
5. 为 Web App 验证回环绑定、同源限制、速率/请求限制、错误响应和与 MCP 的结果模型一致。
6. 用 Playwright 对浏览器星图进行桌面截图与交互验证：WebGL 画布非空、地点/时间
   改变后画面和建议同步、错误状态可见、文字不重叠。
7. 最终验收运行完整既有测试、新增测试、MCP stdio 发现测试和一次受控的端到端
   Web 演示；公网提供方只作为单独 live smoke test，不能使离线 CI 不稳定。

## 9. 非目标

- 不构建小程序或原生移动应用；
- 不自动判断现场安全或发布“必定可观测”的结论；
- 不把 APOD 或其它 NASA 科普内容当作实时星历数据；
- 不把静态卫星辐亮度直接转换成未经校准的 Bortle 等级；
- 不通过 RemoteControl 执行本机脚本、访问非回环地址或暴露用户本机服务给公网。
