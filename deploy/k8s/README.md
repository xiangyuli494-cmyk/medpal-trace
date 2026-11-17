# Kubernetes 演示部署

> 当前清单用于恢复历史 CCE 演示配置。执行前确认资源、预算、镜像版本和数据库可用。
> 本轮仅复核静态配置，没有重新执行云端部署。

## 1. 准备配置

`10-configmap.yaml` 中的非敏感配置需要按实际环境检查。
当前显式选择 gaussdb，因此 Secret 必须包含可用的 `MEDPAL_DB_DSN`。
Deployment 已启用 `imagePullSecrets: swr-secret`，请先创建有效拉取凭据。
桶名统一为历史真机证据的 `medpal-trace-cn4`，部署前确认当前账号有权访问；本轮未查询云端桶状态。

先构建和推送 **0.1.1**，不要复用或覆盖旧 `0.1.0`。旧 tag 的远端 digest 未核验。
新清单使用 `Always` 避免节点复用旧 tag 缓存；正式冻结时将镜像替换为实测 RepoDigest。

```bash
docker build -t swr.cn-north-4.myhuaweicloud.com/medpal/medpal-trace:0.1.1 .
# 完成 SWR 登录后推送，并保存 push 返回的 digest
docker push swr.cn-north-4.myhuaweicloud.com/medpal/medpal-trace:0.1.1
```

Dockerfile 用独立构建阶段编译 crcmod，并在运行镜像安装 psycopg 和 OBS SDK。
SDK 可导入不等于真桶上传通过，仍需部署后的真实上传、下载与内容比对。

在本机创建 `deploy/k8s/medpal.env`，填入模型 Key、数据库 DSN 等真实值；该文件已被忽略。
字段名见 `examples/11-secret.example.yaml`。不要把真实配置填进受跟踪的示例文件。

```bash
kubectl apply -f deploy/k8s/00-namespace.yaml
# 使用包含有效 SWR 登录信息的本机配置文件，不把凭据粘贴进仓库
kubectl -n medpal create secret generic swr-secret --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson=/path/to/swr-docker-config.json
kubectl -n medpal create secret generic medpal-api --from-env-file=deploy/k8s/medpal.env
kubectl apply -f deploy/k8s/
kubectl -n medpal rollout status deployment/medpal-api
```

如果 Secret 已存在，跳过 create；需要更新时显式应用本机填写的 `11-secret.yaml`。
顶层目录 apply 不加 `-R` / `--recursive`，避免应用 examples 下的空模板。
模板已移入子目录，日常重跑顶层 apply 不会更新或清空 Secret。
内存请求已提高到 128Mi，limit 为 1Gi；资源不足时应释放或增加节点容量，不能依赖压低请求获得稳定性。

## 2. 验证边界

先端口转发再调用 `/health`、`/v1/ask` 和 `/v1/traces/{id}`，逐项记录输出。
`/health` 为 200 不代表 PG 已成功保存问答，必须回读同一条 trace。

```bash
kubectl -n medpal port-forward svc/medpal-api 8080:8000
# 另一个终端
curl -s http://127.0.0.1:8080/health
curl -s -X POST http://127.0.0.1:8080/v1/ask -H 'Content-Type: application/json' \
  -d '{"question":"消化性溃疡要做什么检查？"}'
```

存活探针使用无数据库依赖的 `/livez`；就绪探针继续使用 `/health`。
数据库故障时就绪失败会停止接收流量，存活检查不会因此反复重启进程。
Dockerfile 已补 OBS SDK 安装，但构建与真桶验证是不同的验收项目。
APIG 公网接口、修复后完整问答落 PG、50 并发指标也都需要另行复验。
