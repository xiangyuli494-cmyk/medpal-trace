# 端到端验收清单（A9）

> 用途：交付/答辩前照着从上到下跑一遍，任何一条与「期望输出」不符就是回归。
> 每条都写清**命令**、**期望输出**（下面贴的都是本机实测原文，不是示意）和**不符时先看哪里**。
> 覆盖范围：健康检查 → 提问 → 拒答 → 决策链与契约 → 资产 → 本体版本 → 云就绪度 → 演示页 → 评测 → 门禁。

## 0. 前置（只做一次）

```bash
# 1) 环境
python -m venv .venv && . .venv/Scripts/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) 让 Python 找得到 packages/core 与 apps/api（与 scripts/verify.sh 里的口径一致）
export PYTHONPATH="$PWD/packages/core:$PWD/apps/api"                       # Linux / macOS
export PYTHONPATH="$(cygpath -w "$PWD/packages/core");$(cygpath -w "$PWD/apps/api")"  # Windows Git Bash

# 3) 灌数据（**从干净库开始**，否则资产数/版本列表会累积，与本文期望值不符）
rm -f data/medpal.db && rm -rf data/reports && python -m app.seed

# 4) 起服务（另开一个终端；下文用 8127 端口）
python -m uvicorn app.main:app --host 127.0.0.1 --port 8127
```

下文命令统一用 `B=http://127.0.0.1:8127`。

> **必须先激活 venv**：没激活时 Git Bash 里的 `python` 是系统 Python（`~/AppData/Local/Programs/Python/Python312/python`），缺依赖也读不到 `PYTHONPATH`，E11 会直接 `ModuleNotFoundError`。用 `python -c "import sys;print(sys.executable)"` 确认走的是 `.venv` 里的那个。

### ⚠️ Windows / Git Bash 必读

在 Git Bash 里用 `curl -d '{...中文...}'` 会把中文 argv 交给 Windows 的 ANSI 码页，服务端收到的是非法 UTF-8，返回
`{"detail":"There was an error parsing the body"}`（实测发出去 57 字节，正确应是 64 字节，7 个汉字各塌成 1 字节）。
**POST 带中文时一律用 `--data-binary @文件`**，下面 E02/E03/E08/E12 都是这么写的。Linux/macOS 下 `-d` 正常。

## 1. 验收条目

### E01 服务健康

```bash
curl -s $B/health
```

期望（关键字段）：

```json
{"ok":true,"ontology_version":"v1.0","assets":1,"llm":"offline","llm_ready":false,"storage":"sqlite"}
```

不符先看：`assets` 是不是 0（没 seed）、`storage` 是不是期望的后端。

---

### E02 正常提问：有结论、有证据、完整率 1.0

```bash
cat > /tmp/q1.json <<'EOF'
{"question": "上腹隐痛伴反酸，下一步做什么检查？", "top_k": 8, "max_hops": 2}
EOF
curl -s --data-binary @/tmp/q1.json -H 'Content-Type: application/json' -X POST $B/v1/ask
```

期望（关键字段，实测）：

```json
{"ok":true,"trace_id":"TR-20261109-08BD","trace_completeness":1.0,"evidence_count":8,"unresolved":[],
 "conclusion":{"statement":"上腹隐痛 -[提示]-> 消化性溃疡 -[确诊检查]-> 胃镜",
               "dept":"消化内科","exams":["胃镜"],"drugs":["布洛芬"],"evidence_count":8,"conflicts":[]},
 "entities":["上腹隐痛","烧心"]}
```

判定线：`dept == 消化内科` 且 `evidence_count > 0` 且 `trace_completeness == 1.0`。

---

### E03 域外提问：诚实拒答，不编结论

```bash
cat > /tmp/q2.json <<'EOF'
{"question": "如何办理签证？", "top_k": 8, "max_hops": 2}
EOF
curl -s --data-binary @/tmp/q2.json -H 'Content-Type: application/json' -X POST $B/v1/ask
```

期望（实测）：

```json
{"ok":false,"trace_id":"TR-20261109-A292","trace_completeness":1.0,"evidence_count":0,"unresolved":[],
 "conclusion":{"statement":"证据不足，无法给出结论","dept":"","exams":[],"drugs":[],"evidence_count":0},
 "hits":[],"paths":[],
 "gaps":["如何办理签证？","本体里没有可用的推理路径，建议补充三元组或换问法"]}
```

判定线：`evidence_count == 0`、`dept == ""`、`gaps` 非空。**注意**：`trace_completeness` 这里是 1.0 不是 0——「没有引用」不等于「引用错了」，判分口径以 `evidence_count==0` 为准。

---

### E04 空问题：参数校验拦住

```bash
curl -s -o /dev/null -w '%{http_code}' --data-binary '{"question":""}' \
  -H 'Content-Type: application/json' -X POST $B/v1/ask
```

期望输出：

```text
422
```

---

### E05 资产详情（A3 端点）

```bash
curl -s $B/v1/assets/AST-2026-feef2d | head -c 420      # 资产 id 用 $B/v1/assets 查
```

期望（实测，截断）：

```json
{"ok":true,"item":{"asset_id":"AST-2026-feef2d","title":"消化性溃疡临床路径（合成样本）","modality":"text",
 "structure":{"blocks":7,"anchors":7,"kinds":["heading","paragrap…
```

判定线：`item.anchors` 长度为 7，且每条 anchor 都有 `anchor_id` / `kind` / `text`。

---

### E06 资产不存在：404 且 reason 可判

```bash
curl -s -w ' [HTTP %{http_code}]' $B/v1/assets/AST-0000-nope
```

期望输出：

```text
{"detail":{"reason":"asset_not_found","asset_id":"AST-0000-nope"}} [HTTP 404]
```

---

### E07 本体版本列表

```bash
curl -s $B/v1/ontology/versions
```

期望（实测）：

```json
{"ok":true,"items":[{"version":"v1.0","triple_count":8,"manifest_hash":"bf03567152f0132f","is_current":1}]}
```

---

### E08 本体快照 + 版本倒序（造出第二个版本才验得出倒序）

```bash
cat > /tmp/snap.json <<'EOF'
{"version": "v1.1", "note": "e2e 测试"}
EOF
curl -s --data-binary @/tmp/snap.json -H 'Content-Type: application/json' -X POST $B/v1/ontology/snapshot
curl -s $B/v1/ontology/versions | python -c "import json,sys;d=json.load(sys.stdin);print([(x['version'],x['is_current']) for x in d['items']])"
```

期望输出：

```text
[('v1.1', 1), ('v1.0', 0)]
```

判定线：**新的在前**，且只有一个 `is_current==1`。

> 期望值以**干净 seed 库**（只有 v1.0）为前提；库里已有更高版本时列表更长（如 `[('v1.2',1),('v1.1',0),('v1.0',0)]`），只要满足「新的在前 + 只有一个 current」即算过。

---

### E09 云就绪度：没配就明说缺什么

```bash
curl -s $B/v1/cloud
```

期望（本机未配任何华为云变量时，实测）：

```json
{"ok":true,"region":"cn-north-4",
 "ready":{"obs":false,"gaussdb":false,"modelarts":false,"koosearch":false},
 "missing":{"obs":["HUAWEI_AK","HUAWEI_SK","HUAWEI_OBS_BUCKET"],
            "gaussdb":["MEDPAL_DB_DSN","HUAWEI_GAUSSDB_DSN"],
            "modelarts":["HUAWEI_MODEL_ENDPOINT","HUAWEI_MODEL_NAME"],
            "koosearch":["HUAWEI_KOOSEARCH_ENDPOINT"]},
 "storage_backend":"sqlite"}
```

判定线：**四项 `ready` 与 `missing` 必须自洽**——`ready=false` 的项必须在 `missing` 里列出变量名，反过来也一样。这一条是防止「说通了其实没通」。

---

### E10 不存在的 trace：404 且 reason 可判

```bash
curl -s -w ' [HTTP %{http_code}]' $B/v1/traces/TR-19700101-0000
```

期望输出：

```text
{"detail":{"reason":"trace_not_found","trace_id":"TR-19700101-0000"}} [HTTP 404]
```

---

### E11 决策链回读 + 契约校验（最关键的一条）

```bash
cat > /tmp/q3.json <<'EOF'
{"question": "消化性溃疡该挂哪个科？", "top_k": 8, "max_hops": 2}
EOF
TID=$(curl -s --data-binary @/tmp/q3.json -H 'Content-Type: application/json' -X POST $B/v1/ask \
      | python -c "import json,sys;print(json.load(sys.stdin)['trace_id'])")

curl -s $B/v1/traces/$TID | python -c "
import json,sys; d=json.load(sys.stdin)
print('schema=', d['schema']); print('steps=', len(d['steps']))
print('completeness=', d['trace_completeness']); print('refusal=', d['refusal'])"

curl -s $B/v1/traces/$TID | python -c "
import json,sys
from medpal_core.contracts.trace import load_schema
from medpal_core.contracts.trace.validator import validate
print('contract_errors=', validate(json.load(sys.stdin), load_schema()))"
```

期望输出（实测）：

```text
schema= medpal-trace/1
steps= 6
completeness= 1.0
refusal= False
contract_errors= []
```

判定线：`steps == 6`（retrieve / entity_extract / std_align / kg_query / conflict_check / conclude）、`contract_errors == []`。**这条挂了说明冻结契约被破坏，优先级最高。**

---

### E12 演示页可访问 + 三态入口

```bash
curl -s -o /dev/null -w '%{http_code}\n' $B/web/
curl -s $B/web/ | grep -c 'ev-row'
curl -s $B/web/ | grep -o '?demo=[a-z]*' | sort -u
```

期望输出（实测，最新 `main`）：

```text
200
6
?demo=default
?demo=loading
?demo=refusal
```

判定线：`200` + 页面里有证据行骨架 + 三条 `?demo=` 入口都在。三态**画面**（骨架屏 / 拒答卡 / 证据展开标红）需浏览器真实点击，属人工项，见 `docs/design/web-v2.md` §6。

---

### E13 评测（G2 口径 n=60）

```bash
python eval/run_eval.py --dataset v2 --json /tmp/eval.json | grep -E '^(dept_acc|retriever)'
```

期望输出（实测）：

```text
dept_acc=0.967  exam_recall=1.0  completeness=1.0  avg_steps=6.63  avg_ms=5.9  (n=60, dataset=v2.jsonl, zero_evidence=0)
retriever=bm25->bm25  llm=offline->offline  llm_errors=0
```

判定线：`n == 60`、`zero_evidence == 0`、`dept_acc >= 0.85`。`retriever`/`llm` 那行要看**实际后端**，未配置时回落到 `offline` 是正常且必须如实打印的。

> 别用 `tail -2`（会拿到「retriever + 写入 json」两行，把指标行挤掉）；`avg_ms` 每次都变（5.9 / 7.0 都见过），判定线只设 `n` / `dept_acc` / `zero_evidence`。

---

### E14 一键验收（快）：改代码时秒级反馈

```bash
bash scripts/verify.sh --fast
```

期望输出（实测）：

```text
     ok   lint (ruff)
     ok   边界 BND1-BND3
     ok   禁用语
     ok   单元测试 (pytest)
     ok   灌演示数据 (seed)
     ok   端到端冒烟 (smoke)
     ok   模型连通性 (smoke_llm)

PASS
```

---

### E15 一键验收（全量，G2 门槛）

```bash
MIN_N=60 MIN_DEPT_ACC=0.85 bash scripts/verify.sh
```

期望输出（实测）：

```text
     ok   lint (ruff)
     ok   边界 BND1-BND3
     ok   禁用语
     ok   单元测试 (pytest)
     ok   灌演示数据 (seed)
     ok   端到端冒烟 (smoke)
     ok   模型连通性 (smoke_llm)
     ok   指标门槛  n=60 dept_acc=0.967 completeness=1.0 zero_evidence=0

PASS
```

判定线：最后一行必须是 `PASS` 且退出码 0；任何一项 `FAIL` 都会把退出码变成 1。

---

### E16 边界与文案红线

```bash
python tools/check_boundaries.py
python tools/check_guard_words.py
```

期望输出（实测）：

```text
边界检查: 通过
禁用语检查: 通过
```

说明：`check_boundaries.py` 用机器证明「底座可复用」（core 不许 import 应用层、云 SDK 只许在 providers、core 里不许出现行业词）；`check_guard_words.py` 扫 README / docs / data/samples / apps/web，防止把演示说成承诺。

---

### E17 消融四组命令都能跑（A2/A7）

```bash
python eval/run_eval.py --dataset v2 --retriever bm25      --llm offline   --json /tmp/a1.json | tail -1
python eval/run_eval.py --dataset v2 --retriever bm25      --llm modelarts --json /tmp/a2.json | tail -1
python eval/run_eval.py --dataset v2 --retriever koosearch --llm offline   --json /tmp/a3.json | tail -1
python eval/run_eval.py --dataset v2 --retriever koosearch --llm modelarts --json /tmp/a4.json | tail -1
```

期望：四条都打印 `retriever=…->…  llm=…->…  llm_errors=0`，且**未配置的云端项如实回落**并打印出来（不会假装成功）。四组数字与结论见 `eval/ablation.md`。

---

## 2. 已知问题（跑不通时先对照这里）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `sqlite3.IntegrityError: UNIQUE constraint failed: trace.trace_id` | `trace_id` 后四位只有 65536 种，同一天累积几百条后必撞 | **已修（#74）**：查表预检 + INSERT 层 SAVEPOINT 重试。在旧代码上遇到时清库重跑：`rm -f data/medpal.db && rm -rf data/reports && python -m app.seed` |
| 同时打两个以上请求时随机 500，日志 `SQLite objects created in a thread can only be used in that same thread` | FastAPI 把同步依赖与端点调度到不同线程，`storage/db.py` 的 `sqlite3.connect` 没开 `check_same_thread=False` | **已修（#81）**：`connect()` 已开 `check_same_thread=False`。复跑方法见 §4，判据是 48 请求**全部 200** |
| `curl -d` 带中文返回 `There was an error parsing the body` | Windows Git Bash 的 argv 码页问题（见 §0） | 改用 `--data-binary @file` |
| `/v1/assets` 全是 0 条 | 没跑 seed，或 `MEDPAL_DB` 指向了别的库 | 确认 `python -m app.seed` 与 `MEDPAL_DB` 一致性 |

## 3. 一页速查（复制即跑）

```text
E01 health            curl -s $B/health                                    → ok:true
E02 正常提问          POST /v1/ask（--data-binary）                        → dept=消化内科, evidence=8, completeness=1.0
E03 域外拒答          POST /v1/ask 域外问句                                → evidence=0, dept="", gaps 非空
E04 空问题            POST /v1/ask question=""                             → 422
E05 资产详情          GET /v1/assets/{id}                                  → ok:true, anchors=7
E06 资产 404          GET /v1/assets/AST-0000-nope                         → 404 asset_not_found
E07 版本列表          GET /v1/ontology/versions                            → items[0].is_current=1
E08 版本倒序          POST snapshot v1.1 后查列表                          → [('v1.1',1),('v1.0',0)]
E09 云就绪度          GET /v1/cloud                                        → ready 与 missing 自洽
E10 trace 404         GET /v1/traces/TR-19700101-0000                      → 404 trace_not_found
E11 契约校验          GET /v1/traces/{id} + validate()                     → steps=6, contract_errors=[]
E12 演示页            GET /web/ (+ ?demo= 三入口)                        → 200 + ev-row=6 + 三个 demo 参数（实测）
E13 评测 n=60         python eval/run_eval.py                              → n=60 dept_acc>=0.85 zero_evidence=0
E14 门禁（快）        bash scripts/verify.sh --fast                        → 7 项 ok + PASS
E15 门禁（G2）        MIN_N=60 MIN_DEPT_ACC=0.85 bash scripts/verify.sh    → 8 项 ok + PASS
E16 边界/禁用语       check_boundaries.py + check_guard_words.py           → 均「通过」
E17 消融四组          run_eval.py --retriever × --llm 四条                 → 均打印实际后端
```

共 **17 条**，其中 E02/E03/E11/E13/E15 是门槛项（答辩前必须全绿）。

## 4. 最近一次全量复验记录

复验基线是**最新 `main`**（本行随 PR 更新；合并前 rebase 到当时最新的 `main` 再跑一遍，
不要在旧 `main` 上跑完就写「全绿」——#84 改了 `apps/api/app/main.py`、#92 又改了
`scripts/verify.sh`（多一个可选的镜像验收步骤），旧基线跑出来的结果对不上现在的 `main`）。

| 项 | 结果 | 环境 |
| --- | --- | --- |
| 本清单 E01–E17 | 全绿 | 最新 `main`，干净 worktree、**无任何本地补丁** |
| 演示页 A6 验收（证据展开 / 假锚点 0% + 整块标红 / 行内 ❌ / 展开「锚点不存在」） | **21/21 断言通过** | headless Chrome + CDP 真点击 |
| 演示页 A8 验收（三条一键入口 / 加载态固定画面 / 拒答态 / 窄屏 375 单栏且展开不遮挡输入框） | 同上，含在这 21 条里 | 同上 |
| 并发（`/health`+`/v1/ask`+`/v1/traces`+`/v1/assets` 各 12 条，20 线程） | **48/48 全 200** | 验证 #81 生效 |

### 4.1 怎么复核这两条「只有数字」的项

前提与 §0 一致（干净库 + 服务起在 8127 + `PYTHONPATH` 指到 core/api）。

**并发（判据：`total 48 200: 48`，任何一条 500 即 #81 回归）**

```bash
python - <<'EOF'
import json, urllib.request as u, urllib.error, concurrent.futures as cf
B = "http://127.0.0.1:8127"; Q = {"question": "上腹隐痛伴反酸，下一步做什么检查？", "top_k": 8, "max_hops": 2}
def call(path, body=None):
    req = u.Request(B + path, data=json.dumps(body, ensure_ascii=False).encode() if body else None,
                    headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    try:
        with u.urlopen(req, timeout=60) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
tid = json.loads(u.urlopen(u.Request(B + "/v1/ask", data=json.dumps(Q).encode(),
      headers={"Content-Type": "application/json"})).read())["trace_id"]
jobs = []
for _ in range(12):
    jobs += [("/health", None), ("/v1/ask", Q), ("/v1/traces/" + tid, None), ("/v1/assets", None)]
with cf.ThreadPoolExecutor(max_workers=20) as ex:
    codes = list(ex.map(lambda j: call(*j), jobs))
print("total", len(codes), "200:", sum(1 for c in codes if c == 200))
EOF
```

实测输出：`total 48 200: 48`。

**演示页 21 条断言（判据：输出 `演示页验收: 21/21 断言通过`，退出码 0）**

`tools/web_accept.py` 用 headless Chromium + CDP 真点击，覆盖 A6（证据展开原文 / 假锚点 0% +
整块标红 / 行内 ❌ / 展开「锚点不存在」/ 决策链步高亮）与 A8（三条一键入口 / 加载态固定画面 /
拒答态 / 窄屏 375 单栏且展开不遮挡输入框）。不截图、不比像素，纯 DOM 断言。

```bash
python tools/web_accept.py --make-fake     # 自建假锚点 trace 后直接跑（推荐）
python tools/web_accept.py TR-XXXX         # 或跑一条已存在的 trace
python tools/web_accept.py --make-fake --base http://127.0.0.1:8000   # 端口不是 8127
```

以 `--make-fake` 为例，开头打印它造出的 `trace_id`，最后一行是 `演示页验收: 21/21 断言通过`
（中间 21 行 `ok`，逐条见脚本）。假锚点 trace 由 `write_trace()` 写库造出，**资产真实存在、
锚点不存在** —— 前端才会走「锚点不存在（unresolved）」分支；资产也不存在时走的是另一条
「资产不存在」，验不到本项。

> `--make-fake` 要和服务用同一个 `MEDPAL_DB`（否则读不到刚写的 trace），浏览器用 `CHROME=` 指定；
> 跑完库里会多一条 `TR-` 记录和报告，要复位就按 §0 清库重 seed。
