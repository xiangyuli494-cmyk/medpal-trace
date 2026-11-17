# 云资源申请与就绪表（C0 · 11/02 发出）

> 这是关键路径的第一环：**C0 不发出，B6 GaussDB 就开不了工，整条链往后滑**。
> 每拿到一项就把「工单号 / 状态」填上，11/08 前至少 OBS + RDS + ModelArts 三项为「已开通」（**11/03 已完成 OBS 与 RDS，见 §4 实测记录**）。

## 0. 申请前先确认（缺一项会卡住审批）

| 项 | 说明 | 状态 |
| --- | --- | --- |
| 华为云账号 | 已实名认证（个人或学校项目账号） | ☐ |
| 项目 ID | 「我的凭证」里复制 `project_id`，填进 `HUAWEI_PROJECT_ID` | ☐ |
| Region | 统一用 **cn-north-4（北京四）**，四处资源必须同区，否则内网不通 | ☐ |
| 代金券 / 预算 | 校园赛一般有代金券，先确认额度能撑 4 周 | ☐ |
| IAM 子账号 | 给 t2 建一个可管 OBS/GaussDB/CCE 的子账号，别共用主账号密钥 | ☐ |

## 1. 五项资源（一行一项，共 5 行）

| # | 资源 | 用途 | 最低规格 | 申请入口 | 工单号 | 状态 | 负责人 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **OBS 桶** | 存原件 + trace 报告（`obs://` 路径回写库） | 标准存储，单 AZ，1 GB 足够 | 对象存储服务 OBS → 创建桶 | `obs://medpal-trace-cn4` | ✅ **已开通并实测**（put/get/delete 三步自检通过，2026-11-03；2026-11-08 复核 listBuckets 仍 200） | t1 |
| 2 | **RDS for PostgreSQL** | 三元组 / 资产 / trace 元数据 | 单机 2C4G / 40 GB / 按需 | 云数据库 RDS → 购买实例 | `rds-61e6` / PG 18.6 | 🟡 **已开通并实测，实例已释放**（11/03 开通，`scripts/check_pg.py` 九步全绿；因按需计费 ¥0.46/h 于 11/06 删除，2026-11-08 API 复核 `total_count=0`；本地 `postgres:16` 容器保留同构环境） | t1 |
| 3 | **ModelArts Studio** | 大模型推理（结论叙述） | 按 token 计费，开通即用 | ModelArts Studio → 在线推理 → 获取 API Key | 端点 `https://api.modelarts-maas.com/v1` | ❌ **平台侧无可用对话模型**（2026-11-08 全流程探到底：① 域名 DNS 通，无 key → `400 ModelArts.81002`，假 key → `401 ModelArts.81003`，鉴权层正常；② 华北-北京四不支持该服务，须切华东-上海一 / 西南-贵阳一 / 中国-香港；③ 华东-上海一模型广场仅 8 个模型，搜 `deepseek` 命中 0；④ 西南-贵阳一模型广场 40 个，全为盘古 AI4S / 预测 / CV / Embedding **模型资产**，详情页只有「模型介绍 / 版本列表」，无 endpoint、无 API Key、无调用额度；⑤「预置服务」列表为空，顶部写明「并发 0 / 调用 0 次每天」；⑥ 要调用只能点「部署」→ 起算力 → 按小时计费。**结论：不用 ModelArts，推理改走 DeepSeek 官方 API**（同一 OpenAI 兼容客户端，零代码改动；`scripts/smoke_llm.py --strict` 实测 OK，30 条评测指标与离线完全一致，见 [docs/evidence/2026-11-08-deepseek.md](evidence/2026-11-08-deepseek.md)）；`MEDPAL_LLM=offline` 仍为默认，答辩不依赖网络） | t1 |
| 4 | **KooSearch** | 向量 / 语义检索（替代本地 BM25） | 最小规格集群 | 云搜索服务 KooSearch → 购买 | | ❌ **未申请**（服务入口只到 L0 白名单；检索走本地 BM25，`providers/huawei/koosearch.py` 未配置时返回空数组不抛错） | t1 |
| 5 | **计算与网关**（CCE + SWR + APIG） | 容器托管 + 镜像仓库 + 对外域名 | CCE 单节点（2C4G）+ SWR 免费额度 + APIG 共享版 | CCE / SWR / APIG 分别开通 | SWR 组织 `medpal` / 镜像 `swr.cn-north-4.myhuaweicloud.com/medpal/medpal-trace:0.1.0` | 🟡 **SWR 已完成**（镜像 50.3 MB，tag 0.1.0，2026-11-06 推送）；**CCE 未开通**（`clusters` 空；购买页默认 CCE Turbo 高可用 ¥2.91/h ≈ ¥70/天，且仅 master 不含节点；要建须切 CCE Standard + 单控制节点，master 免费只付节点 ≈ ¥0.4/h）；**APIG 未开通**（`/v2/{pid}/instances` 返回 404 APIGW.0101） | t1 |

## 2. 拿到之后填这里（供 `/health` 与 `dev.huawei.sh` 读取）

| 环境变量 | 含义 | 值 |
| --- | --- | --- |
| `HUAWEI_AK` / `HUAWEI_SK` | IAM 子账号密钥 | （不入库，写 `.env.huawei`） |
| `HUAWEI_REGION` | 区域 | cn-north-4 |
| `HUAWEI_PROJECT_ID` | 项目 ID | |
| `HUAWEI_OBS_BUCKET` | 桶名 | |
| `MEDPAL_DB_DSN` | `postgresql://root:***@<地址>:5432/medpal`（通用名优先；旧名 `HUAWEI_GAUSSDB_DSN` 仍兼容） | |
| `HUAWEI_MODEL_ENDPOINT` / `HUAWEI_MODEL_NAME` | 推理地址与模型名 | |
| `HUAWEI_KOOSEARCH_ENDPOINT` | 搜索服务地址（服务开通后控制台给的 endpoint；真实方言下再拼路径） | |
| `HUAWEI_KOOSEARCH_APP_ID` | KooSearch 应用 ID | |
| `HUAWEI_KOOSEARCH_REPO_ID` | 知识库（repo）ID，检索必须带 | |
| `HUAWEI_KOOSEARCH_TOKEN` | 现成的 X-Auth-Token（24 小时有效，调试期图省事用；与下面 IAM 三选一） | |
| `HUAWEI_IAM_USER` / `HUAWEI_IAM_PASSWORD` / `HUAWEI_IAM_DOMAIN` | 用 IAM 账号现换 token（`iam_domain` 留空则用用户名，主账号场景） | |

**KooSearch 两种方言**（由配置自动选，不用改代码）：

| 方言 | 什么时候 | 请求 |
| --- | --- | --- |
| `searchtext` | 配了 `APP_ID` + `REPO_ID` | `POST {endpoint}/v1/{project_id}/applications/{app_id}/uni-search/experience/searchtext`，头 `X-Auth-Token`，体 `{repo_id, content, page_num, page_size}`，读 `doc_list` |
| `raw` | 只有 endpoint（自建网关 / 本地假服务） | `POST {endpoint}`，体 `{query, top_k}`，读 `hits` |

> **要溯源，文档里必须带锚点**：把 `asset_id` + `anchor_id` 写进文档的 `additional_fields`，
> 或标签写成 `asset_id=AST-xxx`、`anchor_id=a3`。两者缺一个，这条命中就不进 evidence
> （不进图表并不意味着检索坏了，`scripts/check_koo.py` 会打印锚点率）。
> 自检：`PYTHONPATH=packages/core:apps/api python scripts/check_koo.py`。

## 3. 拿不到时的降级（照 [docs/04-路线图.md](04-路线图.md) §7 的顺序砍）

| 拿不到 | 降级做法 | 影响 |
| --- | --- | --- |
| KooSearch 批不下来 | 继续用本地 BM25，方案书里写「可切换检索后端」并给对比表 | 少一个云产品，演示不受影响 |
| CCE 批不下来 | 单台 ECS + `docker run`，APIG 仍接上 | 少了容器编排的描述 |
| GaussDB 批不下来 | 本地 Postgres 16（B1 已跑通），保留方言差异说明 | **最痛**，三云真机只剩两云 |
| ModelArts 额度不够 | 演示用 `FakeLLM` + 预录一段真机调用视频 | 结论叙述变成离线文案 |

> 三项**不可降级**：OBS、GaussDB、ModelArts 的真机调用记录（评分要「用了华为云」，不是「写了华为云」）。

## 4. 实测记录

> 下面两段输出由**一次性自检脚本**产生，脚本不入库：
> 正式自检脚本按看板由 t3 在 B1（`check_pg`）/ B2（`check_obs`）交付。
> 这里保留的是「云上确实通了」的证据，不是代码资产。（2026-11-03）
>
> **2026-11-08 更新**：`scripts/check_obs.py` 已入库（B2），下面 §4.1 换成正式脚本在
> **真 OBS**（不是 MinIO）上的七步原样输出；§4.3 补第 5 个坑。

证据原文存在 [docs/evidence/2026-11-03-cloud.md](evidence/2026-11-03-cloud.md)。

### 4.1 OBS：能写能读能删

一次性脚本（2026-11-03）：

```
$ python scripts/check_obs.py
put    [OK] _selftest/hello.txt (200)
get    [OK] 内容一致
delete [OK]
OBS READY: obs://medpal-trace-cn4/_selftest/hello.txt @ cn-north-4
```

正式脚本 `scripts/check_obs.py` 在真 OBS 上七步全绿（2026-11-08，`HUAWEI_OBS_ENDPOINT` 留空走 region 拼域名）：

```
$ python scripts/check_obs.py
1)   [OK] endpoint=https://obs.cn-north-4.myhuaweicloud.com, bucket=medpal-trace-cn4, ak=HPUA***
2)   [OK] esdk-obs-python ok
3)   [OK] 桶 medpal-trace-cn4 就绪
4)   [OK] 上传 obs://medpal-trace-cn4/_selftest/hello.txt
5)   [OK] 下载内容一致 sha256=a7397d9c59a0a534… 长度=26
6)   [OK] 桶内 ls 到 1 个对象，含 _selftest/hello.txt
7)   [OK] 已删除测试对象
OBS READY: obs://medpal-trace-cn4/_selftest/hello.txt @ https://obs.cn-north-4.myhuaweicloud.com
```

清理后复查桶内 `_selftest/` 前缀对象数 = 0，不留垃圾对象。

### 4.2 RDS：`scripts/check_pg.py` 九步全绿

```
$ python scripts/check_pg.py
3) 连接      [OK] PostgreSQL 18.6 on x86_64-pc-linux-gnu
4) 建表      [OK] 表：alias, asset, pending_diff, trace, triple, version
5) 写资产    [OK] 覆盖后 title = PG 自检资产 v2
6) 写三元组  [OK] triple_id = T-6496a4bd
7) 版本快照  [OK] v-pgtest triple_count=1 hash=07ea7173fa357dec
8) 读回      [OK] list_assets 命中，当前共 1 条
9) 清理      [OK]
PG READY: 123.60.223.151:5432/medpal
```

### 4.3 云上踩到的五个坑（本地都测不出来）

| # | 现象 | 根因 | 正解 |
| --- | --- | --- | --- |
| 1 | 桶名带 `.`，SDK 连建连接都证书失败 | 桶名含点会让访问域名变成两级子域，泛域名证书只覆盖一级 | 桶名不带点：`medpal-trace-cn4` |
| 2 | `get` 返回 200 但内容是空的 | `esdk-obs-python` 的 `getObject` 不传 `loadStreamInMemory=True` 时，`resp.body` 是 `buffer=None` 的 `ObjectStream`，`read` 属性也是 `None` | provider 加 `read_body()` 兜底并显式传 `loadStreamInMemory=True` |
| 3 | 接上 RDS 立刻 `syntax error` | `INSERT OR REPLACE` 是 SQLite 私有语法，PG 不认 | 改成 `INSERT ... ON CONFLICT ... DO UPDATE`，两库通用 |
| 4 | `permission denied for schema public` | PostgreSQL **15+** 起默认收回了 `PUBLIC` 对 `public` schema 的 `CREATE`；且默认库 `postgres` 的 owner 是 `rdsAdmin` 不是 `root` | 建一个属于 `root` 的库：`CREATE DATABASE medpal;`，之后代码自动建表，不需要任何授权语句 |
| 5 | 真 OBS 上 `check_obs.py` 第 3 步 `[FAIL] OBS 建桶失败: Conflict` | 桶已存在且属于自己的时候，`createBucket` 回 409，但 `reason` 只有 `"Conflict"`，真因在 `errorCode="BucketAlreadyOwnedByYou"`；MinIO 的文案是别的词，只看 `reason` 一定误判 | `ensure_bucket()` 改判：`status<300` 直接过；409 再 `headBucket` 一次，200 即视为就绪；仍不确定才看 `errorCode` 关键字 |

### 4.4 新环境初始化只需一句 SQL

```sql
-- 在 DAS 的 SQL 窗口执行一次；root 是建库者，随后即拥有该库 public schema 的建表权
CREATE DATABASE medpal;
```

然后：

```bash
export MEDPAL_DB_DSN="postgresql://root:***@<地址>:5432/medpal"
export MEDPAL_DB_BACKEND=postgres
python scripts/check_pg.py
```

### 4.5 公网访问的成本纪律

- 只有本机验证才需要绑 EIP：`¥0.02（IP 保有费）+ ¥0.063（1 Mbit/s 带宽）= ¥0.083/小时`
- **验完三件事一起做**：解绑 EIP → 在 EIP 控制台**释放**（只解绑照收钱）→ 实例「停止」（停机只收存储费）
- 安全组只放自己的出口 IP：`<本机公网IP>/32`，不要 `0.0.0.0/0`（真要放开就只开 5432 一条，验完连同规则一起删）

### 4.6 PostgreSQL 18 真机复验（2026-11-10，一次性实例）

为了把 B6 从「本地 sqlite 假绿」推到真机，临时开了 1 台 RDS for PostgreSQL **18.6**（公网 :5432），全程约 6 分钟，跑完即删。证据在 `docs/cloud-evidence/20261110-rds-final/` 与 `docs/cloud-evidence/20261110-rds-load/`。

```text
== pg    九步全绿                                      PASS  6.0s
4) schema=medpal 表：alias, asset, pending_diff, trace, triple, version
5) 覆盖后 asset_id = AST-2026-…, blocks = 7
6) 8 条 added
7) v-pgtest triple_count=8 hash=…
8) PG 路径数=8, SQLite 路径数=8, 结构一致
9) 保留测试表(--keep)
PG READY

== seed  灌演示数据（样本 + 8 条三元组）                PASS  2.3s
== api   /health storage=gaussdb；cloud.ready.gaussdb=true
         /v1/ask 200 有结论；/v1/traces 可回读           PASS
         statement: 上腹隐痛 -[提示]-> 消化性溃疡 -[确诊检查]-> 胃镜
         dept=消化内科 exams=[胃镜] evidence_count=10 completeness=1.0

== load  c=8 n=40                                      PASS  20.3s
         rps=2.16  p50=3023ms  p95=4504ms
```

压测数字偏慢的原因不是数据库：每请求新建一条 PG 连接（公网 TLS 握手约 150ms），叠加 offline LLM 桩固定约 2.4s。换连接复用 + 真模型后 P95 会变，别把 4504ms 当基线写进答辩。

### 4.7 这次又踩了两个坑（都在控制台层面）

| # | 现象 | 根因 | 正解 |
| --- | --- | --- | --- |
| 6 | 实例公网 IP 的 80/443/22/5432 **全部 6s 超时**，而同一时刻 8.8.8.8:53、baidu:443 均 50ms 通；check-host.net 四节点全 timeout | 默认安全组入方向三条规则的源地址分别是 `default_securitygroup`（自引用）、`default_securitygroup`、`192.168.0.0/24`，**公网来源匹配不上任何一条**，等于没放行 | 入方向加一条：`允许 / IPv4 / 自定义TCP 5432 / 源地址类型改成「IP地址」/ 0.0.0.0/0`。「源地址类型」默认是「安全组」，不改就没有输入框可填 |
| 7 | 换 DSN 仍报 `permission denied for schema public`，且 `select rolsuper` 显示 `root` 不是超管（只有 CREATEDB） | PG15+ 收回 PUBLIC 的建表权，public 的 owner 是 `pg_database_owner`，RDS 上 `root` 也拿不到 | ① 换库 `CREATE DATABASE medpal`（见 4.4）；② 不换库，建自己的 schema 并把 search_path 指过去：`CREATE SCHEMA IF NOT EXISTS medpal; ALTER ROLE root SET search_path TO medpal, public;` 本次用 ②，代码零改动 |

顺带修掉一个真缺陷：`apps/api/app/seed.py` 原来 `from medpal_core.storage import connect`，**绕过 deps 的后端分流**，设了 DSN 仍灌进本地 sqlite（表现为 `triples_added: 0 / dedup: 8` 而 PG 里 asset=0）。改成 `from .deps import open_conn` 之后才真灌到 PG。

### 4.8 一次性实例的标准动作（照抄即可）

```bash
# 1) 建实例后，控制台安全组加 0.0.0.0/0:5432（见坑 6）
# 2) 九步自检：--reset 清上次残留，--keep 让 api 步还有数据可读
MEDPAL_DB_DSN="postgresql://root:***@<公网IP>:5432/postgres" \
  python scripts/cloud_accept.py --only pg,api --allow-remote-drop --reset --port 8043
# 3) 压测（同一后端）
MEDPAL_DB_DSN="..." python scripts/cloud_accept.py --only load --port 8044 \
  --load-concurrency 8 --load-requests 40
# 4) 立刻删实例 + 释放 EIP，回账单页确认归零
```

### 4.9 报告上 OBS：应用侧那 30 行（B7）

OBS 适配器早就跑通过真机，但 **应用一直没调用它**——报告只写本地 `reports/`，所以 B7 欠的是代码不是资源。2026-11-10 补上：

| 位置 | 做的事 |
| --- | --- |
| `apps/api/app/report_store.py` | `ReportStore.upload()` 传 `reports/<trace_id>.md`；`uri()` 回读时先查本进程缓存，再 `headObject` 问一次桶 |
| `providers/huawei/obs.py` | 新增 `uri()` / `exists()`，`put()` 复用同一个拼串处，地址不会两处漂 |
| `POST /v1/ask` | 算完就地传，响应带 `report_uri` 与 `report_upload{key, reason}` |
| `GET /v1/traces/{id}` | **body 不动**（schema 冻结：`additionalProperties=false` + `test_frozen_v1_digest`），地址走响应头 `X-Medpal-Report-Uri` |
| `GET /v1/reports/{id}` | 返回报告 markdown 正文 + 云上地址，演示里「点开一条结论看它从哪来」走这里 |

三条降级/失败路径都有明确返回，端点一律 200：

| 情况 | `report_upload.reason` | 表现 |
| --- | --- | --- |
| 没配 AK/SK/BUCKET | `obs_not_configured` | `report_uri=null`，本地 `reports/` 照常写 |
| 上传抛异常 | `upload_failed` + `error` | 推理结果不丢，只在响应里标出来 |
| 本地报告文件不在 | `report_not_found` | 不会去猜一个打不开的链接 |

自检（离线应看到 null，云上应看到 `obs://<bucket>/reports/TR-xxx.md`）：

```bash
curl -s -X POST localhost:8000/v1/ask -H 'Content-Type: application/json' \
  -d '{"question":"上腹隐痛伴反酸，下一步做什么检查？"}' \
  | python -c "import sys,json;d=json.load(sys.stdin);print(d['report_uri'], d['report_upload'])"
curl -s localhost:8000/v1/traces/TR-XXXX -D- -o /dev/null | grep -i x-medpal-report-uri
```

