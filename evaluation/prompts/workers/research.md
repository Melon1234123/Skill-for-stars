# Research Role Scenario

Use this scenario only to interpret a recorded SDSS image result for research-introduction use. The evaluation script, not the Worker, runs the command and writes `execution.json`, stdout, stderr, the exit code, copied inputs, and all actual output files. Do not create or edit `tool_calls.jsonl` or `execution.json`.

Read the assigned case, preserved image metadata and files, and the CLI contract. Use the real exit code and artifacts only. 不要伪造坐标、图像、来源、成功状态或文件。

Keep SDSS attribution, request parameters, cache state, and processing steps exactly as the artifacts show them. If retrieval failed or image validation failed, retain the structured state rather than supplying guessed imagery or provenance.
