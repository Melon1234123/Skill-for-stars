# Persona 评测与任务生成

StarSkill v0.2 Phase 3 在既有 `starskill.evaluation` 架构中增加了 persona 任务生成，
用于在外部 Agent harness 中模拟不同使用者提出任务后的满意度与可靠性评测。它不替代
既有的 core、variant、failure、open 案例，不修改 `EvaluationCase`、回放证据、评分或
`run.json` 格式。

## Persona

内置 persona 均以强类型 `PersonaProfile` 定义，包含知识水平、目标、偏好回答风格、
期望证据、常见错误和失败敏感度：

| Persona | 主要用途 |
| --- | --- |
| `student` | 学习明确步骤和结论依据 |
| `teacher` | 设计可复现且可检查的课堂活动 |
| `outreach` | 面向公众解释并保留科学限定条件 |
| `amateur_observer` | 获取可执行的观测条件与人工复核项 |
| `undergraduate_researcher` | 练习标准化目录查询和可复现证据 |
| `researcher` | 检查服务、ADQL、选择效应和数据来源 |
| `reviewer` | 独立审查科学性、证据和失败处理 |

## 任务族

生成器在以下任务族之间轮换：`observation`、`catalog_query`、`cone_search`、
`crossmatch`、`ambiguous_input`、`service_failure` 和 `scientific_adversarial`。
任务记录中包含结构化输入、预期工具、所需证据、预期结果及完整 persona 配置。它们是
给外部 harness 的测试输入，不能直接视为已完成的科学计算。

`service_failure` 明确要求如实保存失败证据；`ambiguous_input` 要求先澄清参数；
`scientific_adversarial` 用于检验 Agent 是否纠正“角距离等于真实空间距离”等错误主张。

## 生成命令

安装后使用：

```bash
starskill-eval generate --personas all --tasks 100 --seed 42
```

同一功能也保留在原有评测脚本中：

```bash
.venv/bin/python scripts/evaluate_starskill.py generate \
  --personas student,researcher,reviewer \
  --tasks 30 \
  --seed 42 \
  --output-dir evaluation-runs/persona-seed-42
```

`--personas` 只能是 `all`，或受支持 persona 的逗号分隔列表；不接受未知名称、重复名称或
将 `all` 与具体名称混用。`--tasks` 必须大于零，`--seed` 必须为非负整数。

未提供 `--output-dir` 时，默认输出到
`evaluation-runs/persona-tasks-seed-<seed>/`。输出目录必须是新的或空目录，避免覆盖原有
评测数据。

## 产物与可复现性

每次生成只使用本地 `random.Random(seed)`，不访问网络、不调用 MCP、不执行 Agent 或 LLM。
在相同 StarSkill 版本、persona 选择、任务数和种子下，`tasks.jsonl` 与其 SHA-256 保持一致。

```text
evaluation-runs/persona-tasks-seed-42/
  tasks.jsonl
  manifest.json
```

- `tasks.jsonl`：每行一个 `GeneratedEvaluationTask`，可由外部 harness 逐行加载。
- `manifest.json`：记录 schema 版本、生成器、种子、选择的 persona、任务数、任务族和
  `tasks.jsonl` 的 SHA-256。

## Self-play 与后训练数据

Phase 4 已提供不绑定任何模型厂商的 `AgentProvider` 协议。仓库不会配置 API Key、导入
模型 SDK 或调用 LLM；外部 harness 负责实现 `respond(prompt)`，并返回统一的
`AgentResponse`：Markdown 回答、实际观察到的工具调用和需要保存的文本产物。

```python
from pathlib import Path

from starskill.evaluation import export_post_training_datasets, run_self_play_batch
from starskill.evaluation.personas import generate_tasks

# provider 由仓库外的 harness 实现 AgentProvider，不属于 starskill package。
traces = run_self_play_batch(
    tasks=generate_tasks(personas="all", task_count=100, seed=42),
    provider=provider,
    output_root=Path("evaluation-runs/self-play-seed-42"),
)
datasets = export_post_training_datasets(
    run_root=Path("evaluation-runs/self-play-seed-42"),
    output_dir=Path("evaluation/datasets"),
)
```

每条 self-play 轨迹均保存在独立目录中：

```text
evaluation-runs/self-play-seed-42/<run-id>/
  prompt.json
  response.md
  tool_calls.jsonl
  score.json
  satisfaction.json
  artifacts/
```

`score.json` 至少包含 `task_success`、`scientific_correctness`、`tool_selection`、
`evidence_quality`、`reproducibility`、`persona_satisfaction` 六个 0--1 维度及其
证据理由。默认评分器只核查可观察的任务契约标记，不应替代专家同行评议。Provider 或评分器
异常会如实写为 `status: "failed"` 的零分记录，绝不会伪装成成功回答。

通过以下命令可从已验证的轨迹导出 JSONL 数据；输出目录必须是新的或空目录：

```bash
starskill-eval export-datasets \
  --run-root evaluation-runs/self-play-seed-42 \
  --output-dir evaluation/datasets
```

生成的文件为：

```text
evaluation/datasets/
  regression.jsonl
  successful_traces.jsonl
  preferences.jsonl
```

- `regression.jsonl` 包含每个通过结构校验的轨迹，用于回归评测。
- `successful_traces.jsonl` 仅包含六维核心证据均达标且 persona 满意的轨迹。
- `preferences.jsonl` 仅从同一任务、同一 persona 的两条及以上真实轨迹中选出高分回答和
  低分回答，记录格式为 `prompt`、`persona`、`chosen`、`rejected`、`reasons`。没有有效对比
  时文件会为空，不会合成 rejected 样本。

这些文件是 eval/post-training-ready 数据，仓库不会执行或内置模型 fine-tuning。
