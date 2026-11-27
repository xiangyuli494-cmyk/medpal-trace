# 云端恢复与验收记录（2026-11-23—24，进行中）

> 本文记录首轮本地应用接云及异常资源清理。11/24 随后完成的 CCE/RDS/APIG 真机业务验收、50 并发未达标及最终资源释放，见 [后续完整记录](2026-11-24-cloud-fullchain.md)。下文未完成项是首轮快照。

## 范围

本轮使用本机私有配置，不将密钥、账户标识或费用明细写入仓库。以下区分真实云服务、仅本地执行和仍未通过的项目，未完成项不计作 C10/G3 已达标。

## 1. 已完成：应用报告接真实 OBS

本地 FastAPI TestClient + 临时 SQLite + offline 模型，报告仓库接真实 OBS。使用唯一测试前缀隔离，未覆盖已有报告，没有新建桶。

```text
POST /v1/ask: 200
trace_completeness: 1.0
OBS download bytes: 2157
local report bytes: 2157
raw bytes comparison: equal
sha256: 505ad46f46e9f11d4553e3557260e4f72f8c24bcc32b43c57b8a0eb47e2080ad
GET /v1/reports/{id}: 200, ok=true
GET /v1/traces/{id}: 200, X-Medpal-Report-Uri matches upload
temporary OBS object removed: true
```

报告端点按 read_text 规范化 Windows CRLF，内容比较按换行规范化进行；OBS 下载与本地原始文件另外完成逐字节比较。本项不证明 CCE/RDS/APIG 全链路成功。

11/24 补验本地应用 + 真实 MaaS + 真实 OBS：POST /v1/ask、报告和 trace 回读均为 200，real_narrative=true、llm_error=false、完整率 1.0。报告原始文件与 OBS 下载均为 4972 字节、逐字节一致，SHA256 为 `84d53442a3e4c03b6299d8e061ad7ce7e986283ae4e51cb0db2ba51a7c91ef49`；临时对象已删除。数据库仍为本地 SQLite，不记作 RDS/CCE/APIG 验收。

## 2. 已完成：新镜像推送 SWR

- 源码修复提交：`9ef94b439b1e75c864a92ff9b2604c9aad1cea07`，对应 #96 事务修复；并非 main 已合能力。
- 本地重新构建成功；运行镜像包含 psycopg 和 OBS SDK。
- 推送前核对不存在同名远端 tag，没有覆盖旧 tag。
- 镜像：`swr.cn-north-4.myhuaweicloud.com/medpal/medpal-trace:0.1.1`。
- 远端 RepoDigest：`sha256:350cc133898d48d421722f03ec903fb991801181d96754d0a149ddcb75e984fa`。
- 登录配置放在一次性临时目录，推送后删除；未改动用户全局 Docker 登录配置。

## 3. 已执行但未达标：MaaS 连续延迟

使用真实 MaaS /v2 配置和 deepseek-v4.1-flash-1017，连续 10 次短提示词，max_tokens=128；全部 HTTP 200、有真实非空正文、无 offline 标记。

```text
samples_s = [4.928, 3.615, 4.087, 7.648, 16.313,
             3.328, 4.751, 5.204, 4.630, 5.516]
P50 (sorted[n//2]): 4.928 s
P95 (10 samples, max): 16.313 s
P95 < 8 s: FAIL
```

初次 max_tokens=8 的探测有 HTTP 200 但正文为空，未计入上述 10 次。以上仅为模型短请求，不是应用问答端到端延迟；不得据此宣称云上 50 并发达标。

## 4. 资源创建与清理状态

- 开始前核对北京四 ECS、EVS、EIP、ELB、NAT、CBR、RDS、CCE、APIG、DCS 和 TaurusDB 列表均为空；贵阳 CCE/ECS 亦为空。
- 11/24 补查 CCI：携带区域项目 ID 后，北京四 v1/v2 均 HTTP 200、命名空间数为 0；贵阳一 v1/v2 仍为 HTTP 403 / CCI.01.403122，提示没有 CCI 委托，不能据此认定资源为空。未为核查而新建委托或扩展权限。
- RDS PostgreSQL 不支持 dry_run。预检误用该字段触发了临时实例创建；已禁用脚本，不再将该参数当作 PostgreSQL 的试运行预检。
- 临时实例创建任务失败后曾卡在 BUILD，删除被 DBS.200018 拒绝。11/24 经 t1 授权提交官方工单，支持确认失败创建不收费、不产生备份。首次解锁后删除仍被拒绝，已反馈原工单；支持再次处理后，服务 API 状态变为 CREATE FAIL。
- 11/24 11:53（Asia/Shanghai）重试官方 DELETE 返回 HTTP 202，删除任务已 Completed；随后 RDS 实例列表为空、该实例备份数为 0。北京四 ECS、EVS、EIP、ELB、NAT、CBR、CCE、APIG、VPC、子网列表均为空。该误建空 RDS 的清理已完成，已将结果反馈原工单。跟进见 [处理记录](../release/2026-11-24-cloud-status.md)。
- 该次临时网络和安全组已按唯一任务名称清理；未改动原有 Sys-default 安全组。
- 未再创建其他收费资源；清理不计作完整部署验收。
- 删除前补查 RMS「列举所有资源」，HTTP 200，返回 5 项、next_marker 为空：当时的异常 RDS、已有 OBS 桶、两个默认安全组及一个自动告警主题。清单没有 CCI 资源；该清单仅补充已纳管资源证据，未替代贵阳 CCI 服务接口被拒绝的检查。未改动原有桶、安全组和告警主题。

## 5. 仍待完成

贵阳 CCI 资源复查；CCE/RDS/APIG 正式恢复；同一云端问答在 PG 和 OBS 的回读；50 并发指标；MaaS 延迟改进或如实延期；C10 冻结、tag 和最终提交。以上均不因单项服务调用成功而自动关单。
