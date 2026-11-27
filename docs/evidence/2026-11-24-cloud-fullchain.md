# CCE / RDS / MaaS / OBS / APIG 真机验收（2026-11-24）

本轮使用独立的短时 CCE 集群和 RDS PostgreSQL 18，固定 SWR 镜像 digest，执行真实业务与并发请求。凭据只通过 Kubernetes Secret 注入；不把配置 ready 当作远端成功。

## 环境和执行边界

- 镜像：`swr.cn-north-4.myhuaweicloud.com/medpal/medpal-trace@sha256:350cc133898d48d421722f03ec903fb991801181d96754d0a149ddcb75e984fa`，Pod 实际 imageID 已核对。
- 源码含 #96 的事务修复 9ef94b4，尚未合入 main；CCE v1.36，单节点 c9.xlarge.2。
- 容器 requests 为 100m/256Mi，limits 为 1 CPU/1Gi；initContainer seed，数据库在 medpal schema。
- 运行配置与 #96 静态清单有差异：使用固定 digest、seed initContainer、NodePort 30080，并修复默认 DNS 解析失败。节点、子网及 Pod 指向官方内网 DNS；Pod 使用 dnsPolicy=None。没有修改镜像中的业务代码。
- 第一、第二次问答受 DNS 故障影响，模型/OBS 未成功，未计作通过。修复后重新验收。

## 1. CCE 应用真实问答

集群外访问 NodePort，`/health` HTTP 200、storage=gaussdb、llm=openai。

| 项 | 结果 |
| --- | --- |
| POST /v1/ask | HTTP 200，7.411 秒 |
| 模型 | 有真实 narrative，llm_error=false |
| trace 完整率 | 1.0 |
| PG | 新连接查到同一 trace_id，conclusion 与响应一致 |
| trace / report 回读 | 均 HTTP 200，响应头中的 OBS URI 一致 |
| Pod 报告与 OBS 下载 | 4957 字节，逐字节一致 |
| 报告 SHA256 | f33e72bf753b050b76e6316f791efe47cad16b870b507ed3bf9745661739aa0c |

## 2. 公网 APIG 业务

共享版新建分组返回 APIG.1302（不支持创建新资源），因此本轮使用短时专享版 BASIC。公网入口仅供本次验收；使用独立分组、NONE 认证、GET /health 与 POST /v1/ask 两个路由，后端为同 VPC 的 CCE NodePort。

- 公网 APIG `/health` HTTP 200，storage=gaussdb。
- 公网 APIG `/v1/ask` HTTP 200，15.522 秒，有真实 narrative，llm_error=false，完整率 1.0。
- 该问答的同一 trace 已在 PG 查到；trace 与报告回读成功，报告和 OBS 下载一致。
- OBS 报告 4926 字节，SHA256：`ac0bc356954f2c5155c42acf76b872d214839889e6ead43b2410beef266cbbd3`。

## 3. 50 并发：数据路径成功，模型并发未达标

客户端位于集群外，直接访问公网 NodePort；不是 ELB 压测，不能将此结果写成 B12 的 ELB 验收。

| 指标 | 本轮读数 |
| --- | --- |
| 并发 / 请求数 | 50 / 50 |
| HTTP 200 / 传输错误 | 50 / 0 |
| PG 同一批 trace | 50 条全部查到 |
| 完整率 1.0 / OBS URI | 50 / 50 |
| 真实模型正文 / 模型错误 | 8 / 42；PG 中错误分类均为 HTTP 429 |
| 总时长 / 吞吐 | 18.285 秒 / 2.735 req/s |
| HTTP 响应 P50 / P95 | 2.425 / 14.776 秒 |

延迟统计包含快速降级返回，不能解释为真实模型成功响应的延迟。HTTP 成功不等于模型调用成功；50 并发真实模型验收和 8 秒门槛均未通过。逐请求记录见 [load50.json](../cloud-evidence/20261124-acceptance/load50.json)。

## 4. 清理与后续

本轮共生成 54 条测试 trace，其中 52 份报告成功上传。已按新建测试库的 trace_id 集合删除这 52 个 OBS 对象，并逐个复查不存在；没有清空已有桶。应用命名空间已删除；最终查询 CCE/ECS/EVS/EIP/ELB/RDS/APIG 列表及指定 RDS 备份均为空。临时 VPC、子网、安全组和 SSH 密钥对已删除，原有桶与默认安全组保留。未把停止应用当作停止资源计费。

完整业务请求通过不等于功能冻结完成。#96/#99/#100/#101 的审核与合并、模型 429 及性能问题、ELB 并发口径和贵阳 CCI 查询权限仍需处理；暂不创建 v0.9 tag 或关闭 #34。
