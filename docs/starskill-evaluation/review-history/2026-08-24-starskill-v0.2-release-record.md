# StarSkill v0.2 发布记录

日期：2026-08-24

## 本次范围

本次在不改变既有观测流水线、CLI、`run.json`、provenance、artifact hash 和固定评测
回放格式的前提下，完成 StarSkill v0.2 的 VO Query、MCP、persona 评测与 self-play
数据闭环能力。

## 已完成内容

### Phase 1：VO Query Core

- 新增 `starskill.query` 查询层，使用 IVOA TAP、ADQL、PyVO 与 Astropy Table。
- 新增打包服务允许列表 `src/starskill/data/vo_services.yaml`，仅注册 `simbad`、`vizier`
  与 `gaia`；调用方只能提交服务 ID，不能传递任意远程端点。
- 提供 `describe_table`、`cone_search`、`catalog_query` 与 `tap_query`。
- `tap_query` 只接受单条只读 `SELECT`，强制行数上限与超时，并保存最终 ADQL、端点、
  查询哈希、访问时间、行数与数据来源。
- 每次查询保留 `request.json`、`query.adql`、`result.ecsv`、`provenance.json`。网络、
  超时和服务错误保留为结构化失败证据，不会伪装成成功空结果。

### Phase 2：MCP

- 新增 `astronomy_describe_table`、`astronomy_cone_search`、
  `astronomy_catalog_query`、`astronomy_tap_query` 四个 MCP 工具。
- MCP 请求沿用 Pydantic 强类型模型，输出统一包含 `ok`、`status`、`service`、
  `row_count`、`resources` 与 `provenance`。
- 查询产物仅以服务端拥有的 `query-request`、`query-adql`、`query-result`、
  `query-provenance` 资源名暴露，Agent 无法绕过允许列表访问任意 URL。

### Phase 3：Persona 评测

- 在既有 `starskill.evaluation` 模块中新增七类 persona：`student`、`teacher`、
  `outreach`、`amateur_observer`、`undergraduate_researcher`、`researcher`、`reviewer`。
- 每个 persona 都定义知识水平、目标、回答偏好、期望证据、常见错误与失败敏感度。
- 新增七类确定性任务族：观测、目录查询、圆锥查询、交叉匹配、歧义输入、服务失败、
  科学对抗。
- 新增 `starskill-eval generate --personas all --tasks 100 --seed 42`；生成过程只使用本地
  种子随机数并输出可复现的 `tasks.jsonl` 与 `manifest.json`。

### Phase 4：Self-play 与后训练数据

- 定义 provider-neutral 的 `AgentProvider` Protocol；仓库内未配置 API Key、未调用 LLM
  SDK，也不执行模型微调。
- 每条轨迹保存 `prompt.json`、`response.md`、`tool_calls.jsonl`、`score.json`、
  `satisfaction.json` 与 `artifacts/`。
- 默认评分包含 `task_success`、`scientific_correctness`、`tool_selection`、
  `evidence_quality`、`reproducibility`、`persona_satisfaction` 六个维度。默认评分器只做
  可观察的契约检查，不能替代科学同行评议。
- 新增 `starskill-eval export-datasets`，从经过结构校验的轨迹导出：
  `evaluation/datasets/regression.jsonl`、`successful_traces.jsonl`、
  `preferences.jsonl`。偏好数据只从同一任务的真实高低分轨迹配对产生，不合成 rejected 回答。

## 主要文件

- 查询与允许列表：`src/starskill/query/`、`src/starskill/data/vo_services.yaml`
- MCP 接口：`src/starskill/mcp_server.py`、`docs/mcp-server.md`
- Persona 与 self-play：`src/starskill/evaluation/personas.py`、
  `src/starskill/evaluation/persona_cli.py`、`src/starskill/evaluation/self_play.py`
- 评测模型与脚本：`src/starskill/evaluation/models.py`、
  `src/starskill/evaluation/__init__.py`、`scripts/evaluate_starskill.py`
- 中文说明：`docs/vo-query-core.md`、`docs/persona-evaluation.md`、`README.md`
- 新增测试：VO Query、MCP Query、persona 生成、self-play 与数据集导出测试。

## 验证结果

以下验证均在仓库根目录执行并返回成功：

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/python -m pip check
git diff --check
```

- 全量测试通过，无失败。
- `pip check` 返回 `No broken requirements found.`
- `starskill`、`starskill-mcp`、`starskill-eval generate`、
  `starskill-eval export-datasets` 的帮助入口正常。
- wheel 构建成功，并从 wheel 安装目录验证了 query registry、persona generator、
  self-play exporter 和打包的 `vo_services.yaml`。
- 离线端到端演练成功生成 14 条任务；同一目录查询任务的完整轨迹得分 `1.0`、不完整轨迹
  得分 `0.0`；导出 2 条 regression、1 条 successful trace 和 1 个真实 preference 对。

## 已知边界

- 单元测试通过 fake TAP backend 运行，不访问公共 TAP 服务；公共服务的实时可用性不在本次
  离线验证结论中。
- 外部 Agent harness 尚未接入真实模型；本次不声明模型能力、线上 Agent 效果或模型微调结果。
- 第三方依赖会输出 Starlette/httpx 弃用警告与 `pydantic-settings` 前向引用警告，均未影响
  测试、构建或命令退出码。
