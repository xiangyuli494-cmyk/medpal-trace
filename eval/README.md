# 评测口径

评测只看三件事，且三者都能被第三方复现：

1. **答案对不对** —— «dept_acc» / «exam_recall»，gold 来自 «eval/dataset/v2.jsonl»（`--dataset` 不指定时自动优先 v2，没有才退回 v1）。
2. **说得清不清** —— «completeness»，即决策链里每条证据都能被 «_evidence_exists» 核对到的比例。
3. **跑得快不快** —— «avg_ms»，离线模型下的端到端耗时。

数据集现在 **30 条**（[dataset/v2.jsonl](dataset/v2.jsonl)）：6 条保留自 v1（标 `source=manual`），
24 条新增（标 `source=synthetic`），覆盖检查 / 科室 / 病因诱因 / 病原 / 复查五类意图，问句无重复。
`source` 只允许 `synthetic` 与 `manual` 两种；扩到 60 条（A5）继续加 jsonl 行，评测口径不变。
不追求刷分数，追求评委当场重跑得到同一组数字。

## 消融（A2）：检索 × 模型 四组

四组命令都能跑完并打印 `n=30`，不抛异常：

```bash
python eval/run_eval.py --retriever bm25      --llm offline     # 基线（默认）
python eval/run_eval.py --retriever bm25      --llm modelarts
python eval/run_eval.py --retriever koosearch --llm offline
python eval/run_eval.py --retriever koosearch --llm modelarts
```

规则（避免「假云端」）：

- 云端项未配置时**诚实回落并打印 `[warn]`**：koosearch 缺 `HUAWEI_KOOSEARCH_ENDPOINT` 时召回为空但照跑；
  modelarts 缺 `MEDPAL_LLM_BASE_URL` 时回落 offline。报告里同时记录 `requested -> actual`，
  `llm_errors` 统计带 `llm_error` 的条数（模型调用失败不影响整链）。
- 对比表（A7）里的数字必须来自真实配置的那一组，回落组要标明，不许混写。

