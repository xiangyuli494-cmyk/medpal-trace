# 消融实验（A7）

> 目的：把「结论对不对」和「说得清不清」拆开，分别看**检索**和**模型**这两个可替换部件各贡献多少。
> 结论先说：**当前四组里真正起作用的只有本体，检索器和模型换谁来都不动结论质量** —— 这不是好消息，是「云端两项还没真接上」的证明，详见 §5。

## 1. 实验设置（照这张表就能重跑）

| 项 | 值 |
| --- | --- |
| 数据集 | `eval/dataset/v2.jsonl`，**n = 60**（6 条 `manual` + 54 条 `synthetic`；问句重复率 0） |
| 本体版本 | `v1.0`（1 份资产、8 条三元组、7 个锚点） |
| 两个维度 | 检索 `bm25 \| koosearch` × 模型 `offline \| modelarts` |
| 环境 | Windows 11 + Python 3.12（venv）、SQLite；**未配置 KooSearch 实例，未配置 ModelArts key** |
| 每组库 | 每组一套独立临时库（`MEDPAL_DB` 指向新文件 + 先 `python -m app.seed`），避免上一组的 trace 影响下一组 |

四条命令（仓库根目录，`PYTHONPATH` 见 `eval/README.md`）：

```bash
python eval/run_eval.py --dataset v2 --retriever bm25      --llm offline   --json out/bm25-offline.json
python eval/run_eval.py --dataset v2 --retriever bm25      --llm modelarts --json out/bm25-modelarts.json
python eval/run_eval.py --dataset v2 --retriever koosearch --llm offline   --json out/koosearch-offline.json
python eval/run_eval.py --dataset v2 --retriever koosearch --llm modelarts --json out/koosearch-modelarts.json
```

## 2. 四组结果

每组样本量都是 **n = 60**。「实际后端」一列取自 `report.json` 的 `retriever.actual` / `llm.actual`，是脚本自己承认的结果，不是我们的说法。

| # | 组 | 检索（请求 → 实际） | 模型（请求 → 实际） | n | dept_acc | exam_recall | completeness | 零证据条数 | 平均步数 | 平均耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | bm25 + offline | bm25 → bm25 | offline → offline | 60 | 0.967 | 1.000 | **1.000** | 0 | 6.63 | 5.7 ms |
| 2 | bm25 + modelarts | bm25 → bm25 | modelarts → **offline（回落）** | 60 | 0.967 | 1.000 | **1.000** | 0 | 6.63 | 6.0 ms |
| 3 | koosearch + offline | koosearch → koosearch（未配实例） | offline → offline | 60 | 0.967 | 1.000 | **0.983** | 1 | 6.63 | 4.8 ms |
| 4 | koosearch + modelarts | koosearch → koosearch（未配实例） | modelarts → **offline（回落）** | 60 | 0.967 | 1.000 | **0.983** | 1 | 6.63 | 4.8 ms |

**读数要点**

- 第 1、2 组数字完全相同，第 3、4 组也完全相同 —— 说明 `--llm` 这一维**没有产生任何效果**。
- 四组的 `dept_acc` / `exam_recall` / `avg_steps` 完全一致，只有 `completeness` 在第 3、4 组掉了 0.017。

## 3. 差异逐条对：四组之间只有 1 条样本不同

| 问句 | 组 1、2 | 组 3、4 |
| --- | --- | --- |
| 胃溃疡该挂哪个科？ | dept ✗，证据 8 条，completeness 1.000 | dept ✗，证据 **0 条**，completeness **0.000** |

其余 59 条在四组里逐字段相同。

`dept_acc = 0.967` = 58/60，两条 MISS 是 A1 就**刻意保留**的边界样本，不是这次消融造成的：

| MISS 样本 | 原因 |
| --- | --- |
| `胃溃疡该挂哪个科？` | 词表里有「胃溃疡」，但本体没有连边（只有「消化性溃疡」这条链） |
| `反酸烧心该去哪个科？` | 金标是消化内科，但需要 3 跳，超过 `max_hops=2` |

这两条按「暴露短板、不刷分」保留，gold 从未为了对齐输出而改动。

## 4. 结论（≤300 字）

四组里只有检索维度产生了差异，模型维度没有：`--llm modelarts` 两组因为本机未配 `MEDPAL_LLM_BASE_URL`，都回落到 offline，数字与 bm25+offline 一字不差，所以这次「模型消融」实际没有测到模型。检索维度换 koosearch 后，科室准确率与检查召回一动没动（都是 0.967 / 1.000），只有溯源完整率从 1.000 掉到 0.983，差的是一条「胃溃疡该挂哪个科？」——该问句在本体里没有可用路径，bm25 还能召回一段文本凑成证据，koosearch 召回为空后这条直接变成零证据。合起来看：**结论质量由本体三元组决定，检索器换成什么都不改结论**。这既是「底座可移植」的工程证据，也说明云端两项都还没真接上，G2 的真机消融必须重跑。

## 5. 口径与局限（必须连这段一起看，否则上表会被误读）

1. **模型维度没有真消融**。`--llm modelarts` 要求 `MEDPAL_LLM` 属于云端 provider 且 `MEDPAL_LLM_BASE_URL` 非空；本机两者都没有，脚本如实回落到 offline 并在 `llm.actual` 里标出来（没有偷偷冒充云端结果）。接上真实端点后必须重跑第 2、4 组。
2. **检索维度是「未配实例」口径**。KooSearch 没有实例，`build_retriever` 返回的实例 `available()` 为假、召回为空。之所以只影响 1 条，是因为本系统证据主要来自**本体路径的 provenance**（`T-xxxxxxxx` 与 `ASSET#anchor`），不依赖检索命中——这正好解释了为什么换检索器动不了结论。
3. **样本量只有 60，且只有 1 份资产**。指标差异落在 1/60 量级时，不要读成「koosearch 更差」，只能读成「这一条更强依赖检索兜底」。
4. **一个必须记下来的稳定性问题**：本次 `bm25 + offline` 第一次运行直接崩在
   `sqlite3.IntegrityError: UNIQUE constraint failed: trace.trace_id`。
   `trace/writer.py` 的 `trace_id` 只有 4 位十六进制（65536 种），60 条一次评测就有约 2.7% 的碰撞概率，碰撞时**没有重试**，整组评测中断。上面的数字是清库重跑一次后得到的。这条已作为缺陷转给 t1（建议碰撞时重抽一次，或把后 4 位扩到 6 位）；`verify.sh` 用临时库，撞上同样会红。

## 6. 复现与原始数据

- 命令见 §1；每组 `--json` 的输出是本表的唯一来源。
- 复跑前请**清库**：`rm -f data/medpal.db && rm -rf data/reports`，再 `python -m app.seed`，否则老 trace 累积会显著抬高 §5.4 的碰撞概率。
- 验证门禁：`MIN_N=60 MIN_DEPT_ACC=0.85 bash scripts/verify.sh`（本分支实测 PASS）。

## 7. 2026-11-16 适配层复核

PR #94 修复了完整锚点重复加前缀、云端配置不全时误报就绪，以及严格自检对零召回/零锚点的假通过。
四组各 60 条在临时库复跑后，准确率、召回率、完整率与上表一致；BM25 两组平均耗时为 3.9/3.8 ms，
未配置 KooSearch 两组为 3.3/3.3 ms。没有实例，不能用这些数字宣称完成真实云端消融。
细节和剩余验收见 [C5 复核记录](../docs/evidence/2026-11-16-c5-review.md)。
