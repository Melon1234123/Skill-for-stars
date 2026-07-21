# 第 5 天：完整流水线、日志与报告

## 完成内容

`starskill run` 把前四天的独立能力串成一个可审计闭环：读取并校验任务 JSON，解析目标，计算目标、太阳和月亮星历，筛选候选观测窗口，绘制高度角曲线，最后生成结构化结论、运行清单、文字报告和人工复核清单。

真实案例使用 `examples/observation_m42_beijing.json`。第二次运行命中目标缓存，结果保存在 `runs/day5_m42`。

```powershell
python -m starskill run examples\observation_m42_beijing.json `
  --output-dir runs\day5_m42 `
  --cache-dir cache\targets `
  --min-target-altitude-deg 30 `
  --max-sun-altitude-deg -12
```

## 真实运行结果

| 项目 | 结果 |
| --- | --- |
| 运行状态 | `success` |
| 运行编号 | `20260719T101836Z-m-42` |
| 目标缓存 | 命中 |
| 问题记录 | 0 条 |
| 清单登记产物 | 9 个 |
| 候选窗口 | 北京时间 2026-01-10 19:40 至次日 01:20 |

该窗口只表示目标高度不低于 30 度且太阳高度不高于 -12 度。天气、云量、场地遮挡、设备和现场安全仍需人工确认。

## 输出契约

- `input.json`：补齐默认值后的运行输入；
- `run.json`：运行编号、起止时间、状态、依赖版本、来源、缓存、问题和产物校验信息；
- `result.json`：目标、星历、规则和候选窗口的结构化结果；
- `intermediate/target_resolved.json`：SIMBAD 目标解析结果；
- `intermediate/ephemeris.csv` 与 `ephemeris.json`：49 个星历采样；
- `intermediate/visibility.csv`：逐点规则判断与拒绝原因；
- `figures/visibility_curve.png`：1800×900 高度角曲线；
- `report.md`：区分计算事实、规则判断和限制的报告；
- `review_checklist.md`：天气、场地、设备、时间和安全的人工复核入口。

`run.json` 为每个登记产物保存相对路径、字节数和 SHA-256，可用于判断文件是否被替换或损坏。

## 失败与降级

- 输入或阈值不符合模型时返回退出码 `2`；
- 目标未找到返回 `3`，SIMBAD 服务失败返回 `4`；
- 绘图失败时状态为 `degraded`、退出码为 `5`，JSON/CSV 和问题记录仍会保留；
- 数据查询失败会写入失败状态的 `run.json`，不会生成伪造的成功结果或报告。

自动化测试覆盖成功闭环、缓存复用、清单哈希、绘图降级和 SIMBAD 失败路径。
