# Kubernetes 演示部署

> 当前清单用于恢复历史 CCE 演示配置。执行前确认资源、预算、镜像版本和数据库可用。
> 本轮仅复核静态配置，没有重新执行云端部署。

## 1. 准备配置

`10-configmap.yaml` 中的非敏感配置需要按实际环境检查。
当前显式选择 gaussdb，因此 Secret 必须包含可用的 `MEDPAL_DB_DSN`。
私有 SWR 镜像还需在 Deployment 中配置 imagePullSecrets。

在本机创建 `deploy/k8s/medpal.env`，填入模型 Key、数据库 DSN 等真实值；该文件已被忽略。
字段名见 `examples/11-secret.example.yaml`。不要把真实配置填进受跟踪的示例文件。

```bash
kubectl apply -f deploy/k8s/00-namespace.yaml
kubectl -n medpal create secret generic medpal-api --from-env-file=deploy/k8s/medpal.env
kubectl apply -f deploy/k8s/
kubectl -n medpal rollout status deployment/medpal-api
```

如果 Secret 已存在，跳过 create；需要更新时显式应用本机填写的 `11-secret.yaml`。
顶层目录 apply 不加 `-R` / `--recursive`，避免应用 examples 下的空模板。
模板已移入子目录，日常重跑顶层 apply 不会更新或清空 Secret。

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

当前镜像未安装 OBS SDK，不能将配置了桶名解释为报告上传已经通过。
安装 SDK 并完成真桶验证前，报告上传能力保持未验收状态。
APIG 公网接口、修复后完整问答落 PG、50 并发指标也都需要另行复验。
