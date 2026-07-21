# 第 7 天：智能体 Skill 包装

## 交付内容

`skills/run-starskill` 把稳定后的 CLI 包装成可供 Codex 智能体选择和执行的技能。技能只负责工作流选择、调用顺序、错误处理、产物检查和人工复核边界，不复制 Python 实现。

技能目录包含：

- `SKILL.md`：触发场景、工作流选择、执行和复核规则；
- `agents/openai.yaml`：显示名称、简短描述和默认提示；
- `references/cli-contract.md`：命令、参数、输出、退出码和网络边界。

## 工作流选择

| 用户目标 | 命令 |
| --- | --- |
| 生成完整 M42 观测审计包 | `starskill run` |
| 计算月亮与木星位置关系 | `starskill relationship` |
| 获取并处理 M51 SDSS 图像 | `starskill fetch-image` |
| 只做某个中间步骤 | `validate`、`resolve`、`ephemeris` 或 `plan` |

智能体必须检查命令退出码和实际产物，不能把候选观测窗口描述为天气或安全保证，也不能在外部服务失败时伪造坐标、图像或成功报告。

## 本次交付边界

第 7 天原路线包含技术报告和答辩材料。当前交付已完成 Markdown 技术报告与 Skill 包；根据用户要求，展示 PPT 不制作，也不作为完成任务的验收条件。
