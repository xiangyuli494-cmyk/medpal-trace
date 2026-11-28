# 云端恢复前检查（2026-11-22）

## 当前资源（只读 API 实查）

区域：cn-north-4。鉴权读取本机未跟踪配置，未向日志输出密钥。

| 项目 | 本次结果 |
| --- | --- |
| IAM 项目查询 | HTTP 200，找到北京四项目 |
| CCE 集群列表 | HTTP 200，0 个 |
| RDS 实例列表 | HTTP 200，0 个 |
| APIG 实例列表 | HTTP 200，0 个 |
| APIG 共享版 API 列表 | HTTP 200，0 个 |
| 已配置 OBS 桶 HEAD | HTTP 200；未执行上传或删除 |
| MaaS | 本机存在配置；本轮未调用，不代表模型额度或调用已验证 |

本轮没有创建、购买、修改或删除任何云资源。历史 Pod / RDS 证据不能表示当前在线。

## PR #96 的本地事务修复

基于 #96 `6727925`，独立分支 `fix/C10-cloud-preflight`；本记录为提交前证据，远端审核和合并状态以 PR #96 为准。

- `gaussdb.prepare()` 在 DDL 成功后提交，避免首个只读请求关闭连接时回滚建表。
- `check_pg._drop_tables()` 显式提交，避免清理被回滚却报告成功。
- 保持普通事务模式，未重新开启全局 autocommit，SAVEPOINT 路径保持可用。
- `tests/test_pg_transactions.py` 补两项真实 PG 回归；仅接受显式本机测试 DSN，每项测试使用独立 schema，默认无 DSN 时跳过。

## 实测结果

完整 `scripts/verify.sh`：PASS；n=60、dept_acc=0.967、completeness=1.0、zero_evidence=0。11/23 提交前再次执行完整验收及两项真实 PG 回归，均通过。
真实 PostgreSQL 16 一次性本地容器：

```text
first /health: 200
new connection to_regclass('asset'): asset
second /health: 200
/livez: 200
first check_pg.py: exit 0; tables after cleanup: 0
second check_pg.py: exit 0
tests/test_pg_transactions.py: 2 passed
ruff check .: passed
git diff --check: passed
```

容器无宿主机数据挂载，仅绑定环回地址，结束后停止并自动删除。没有接触真实云数据库。

## 云端验收剩余步骤

1. 确认预算上限，取得 CCE 工作节点、RDS、APIG 方案的当前实际报价；创建前确认配置与清理安排。
2. 本地修复获得独立审核；构建新镜像，推 SWR 并固定实际 digest。
3. 恢复网络、安全组、数据库连接、Secret、CCE 部署和 APIG 路由。
4. 真问答、同一 trace 的 PG 回读、OBS 上传及内容比对、MaaS 真调用与连续延迟验收。
5. 按原任务验证 50 并发错误率与 P95；不因配置 ready 或单次成功就标完成。
6. 核实验收证据与清理结果后再决定 C10 冻结。KooSearch 无实例仍沿用此前待办，不计为已通过。
