# VO 查询核心

StarSkill v0.2 第一阶段新增了可离线测试、兼容 IVOA 的查询核心。它使用
IVOA TAP、ADQL、PyVO 和 Astropy `Table`，不会改变既有观测流水线、CLI 命令、
运行包或评测格式。

## 受限服务注册表

随包发布的 [`vo_services.yaml`](../src/starskill/data/vo_services.yaml) 仅允许以下
TAP 服务：

| 服务 ID | 服务 | 默认表 |
| --- | --- | --- |
| `simbad` | CDS SIMBAD TAP | `basic` |
| `vizier` | CDS VizieR TAP | `I/355/gaiadr3` |
| `gaia` | ESA Gaia Archive TAP+ | `gaiadr3.gaia_source` |

请求只能指定 `service` ID，不能传入端点 URL。未知 ID 会在发起网络请求前被拒绝，
因此 Agent 无法借由此接口访问任意远程服务。

## Python 接口

每次 Python 查询必须使用一个新的输出目录：

```python
from pathlib import Path

from starskill.query import CatalogQueryRequest, catalog_query

request = CatalogQueryRequest(
    service="gaia",
    table="gaiadr3.gaia_source",
    columns=["source_id", "phot_g_mean_mag"],
    filters=[{"column": "phot_g_mean_mag", "operator": "<", "value": 12}],
    max_rows=100,
    timeout_seconds=30,
)
result = catalog_query(request, output_dir=Path("runs/gaia-bright"))
```

可用操作如下：

- `describe_table(TableDescriptionRequest, output_dir=...)`：读取一个已校验表名的
  `TAP_SCHEMA.columns`。
- `cone_search(ConeSearchRequest, output_dir=...)`：由强类型坐标和半径构建 ICRS
  ADQL `CONTAINS(POINT, CIRCLE)` 查询。
- `catalog_query(CatalogQueryRequest, output_dir=...)`：由强类型列和过滤条件构建受限
  的 `SELECT TOP` 查询。
- `tap_query(TapQueryRequest, output_dir=...)`：面向注册表服务的高级 ADQL 接口，只允许
  单条只读 `SELECT`；会拒绝注释、分号、写操作关键字和调用方自带的 `TOP` 子句。

所有请求模型都将 `max_rows` 限制在 1--10,000、超时限制在 1--120 秒。最终 ADQL 始终
携带权威行数限制，并以 `maxrec` 同时传给 PyVO。

## 证据与失败处理

每次已执行的允许列表查询都会写入以下可移植产物：

```text
request.json
query.adql
result.ecsv
provenance.json
```

`provenance.json` 会记录操作、服务 ID 与名称、允许列表 TAP 端点、最终 ADQL、
查询 SHA-256、访问时间、返回行数、数据来源机构、行数限制、超时和状态。
`QueryResult.artifacts` 还会给出每个文件的 SHA-256 与字节数。

超时、网络故障和 TAP 服务错误都会返回
`QueryResult(ok=False, status="failed", ...)`，绝不伪装为“成功但无结果”。对应的
`result.ecsv` 是带失败代码的显式空证据文件，`provenance.json` 也包含同一结构化失败。

单元测试通过注入 fake `TapBackend` 返回内存中的 Astropy 表，或抛出受控错误；测试套件
不会访问公网 TAP 服务。

## MCP 工具

本地 `starskill-mcp` 服务以受限形式暴露同一组操作：
`astronomy_describe_table`、`astronomy_cone_search`、
`astronomy_catalog_query` 和 `astronomy_tap_query`。每个工具的 `request` 输入都是对应的
Pydantic 模型，均不接受端点或输出路径。

每个 MCP 响应都包括 `ok`、`status`、`service`、`row_count`、`resources` 和
`provenance`。无论成功或失败，已执行查询只暴露服务端拥有的固定资源：
`query-request`、`query-adql`、`query-result`、`query-provenance`，它们分别对应上文的四类
证据文件。
