# 万象积木 — K3s 部署文档

> Helm Chart 部署指南 | 更新日期: 2026-06-21

---

## 目录

- [1. 架构概览](#1-架构概览)
- [2. 前置条件](#2-前置条件)
- [3. 安装部署](#3-安装部署)
- [4. 服务清单](#4-服务清单)
- [5. 扩缩容](#5-扩缩容)
- [6. 备份恢复](#6-备份恢复)
- [7. 故障排查](#7-故障排查)
- [8. 配置说明](#8-配置说明)

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                      K3s 集群（3 节点最小 HA）                     │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │  Master-1        │  │  Master-2        │  │  Master-3      │ │
│  │  etcd + API      │  │  etcd + API      │  │  etcd + API    │ │
│  │  Traefik Ingress │  │  Traefik Ingress │  │  Traefik       │ │
│  │  api-server      │  │  api-server      │  │  api-server    │ │
│  │  gateway         │  │  gateway         │  │  gateway       │ │
│  │  prometheus      │  │  grafana         │  │  otel          │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                      │
│  │  Worker-1 (GPU)  │  │  Worker-2 (GPU)  │                      │
│  │  16C / 64G / T4  │  │  16C / 64G / T4  │                      │
│  │  model-router    │  │  model-router    │                      │
│  │  orchestrator    │  │  orchestrator    │                      │
│  │  rag-service     │  │  rag-service     │                      │
│  │  embedding-svc   │  │  sd-service      │                      │
│  │  tool-sandbox    │  │  tool-sandbox    │                      │
│  │  skill-runtime   │  │  skill-runtime   │                      │
│  └──────────────────┘  └──────────────────┘                      │
│                                                                  │
│  外部服务: PostgreSQL | Redis Cluster | Qdrant | ES | MinIO | Vault│
└─────────────────────────────────────────────────────────────────┘
```

**总计：~34 Pods，~40 CPU，~80GB RAM，2× NVIDIA T4**

---

## 2. 前置条件

### 2.1 K3s 集群

```bash
# 安装 K3s（Master 节点）
curl -sfL https://get.k3s.io | sh -

# 验证
kubectl get nodes

# 获取 kubeconfig
sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config
```

### 2.2 Helm 3

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

### 2.3 NVIDIA GPU Operator（GPU 节点）

```bash
# 添加 NVIDIA Helm 仓库
helm repo add nvidia https://nvidia.github.io/gpu-operator
helm repo update

# 安装 GPU Operator
helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace

# 验证 GPU 可用
kubectl get nodes -o json | jq '.items[].status.capacity["nvidia.com/gpu"]'
```

### 2.4 存储类

K3s 默认提供 `local-path` 存储类，适用于开发/测试。生产环境建议使用 Longhorn 或 Rook-Ceph。

```bash
kubectl get storageclass
# 确认 local-path 存在
```

### 2.5 密钥配置

```bash
# 创建命名空间
kubectl create namespace wanxiang-production

# 创建镜像拉取凭证
kubectl create secret docker-registry registry-credentials \
  --namespace wanxiang-production \
  --docker-server=registry.wanxiang.ai \
  --docker-username=<username> \
  --docker-password=<password>

# 创建应用密钥
kubectl create secret generic wanxiang-secrets \
  --namespace wanxiang-production \
  --from-literal=database-url='postgresql://user:pass@pg-host:5432/wanxiang' \
  --from-literal=redis-url='redis://redis-host:6379/0' \
  --from-literal=qdrant-url='http://qdrant-host:6333' \
  --from-literal=elasticsearch-url='http://es-host:9200' \
  --from-literal=grafana-admin-password='your-secure-password'

# 创建 TLS 证书
kubectl create secret tls wanxiang-tls \
  --namespace wanxiang-production \
  --cert=path/to/cert.pem \
  --key=path/to/key.pem
```

---

## 3. 安装部署

### 3.1 测试环境部署

```bash
# 部署到 staging
helm upgrade --install wanxiang ./deploy \
  -f ./deploy/values-staging.yaml \
  --set global.imageTag=$(git rev-parse --short HEAD) \
  --namespace wanxiang-staging \
  --create-namespace \
  --wait --timeout 10m

# 验证
kubectl get pods -n wanxiang-staging
kubectl get svc -n wanxiang-staging
kubectl get ingress -n wanxiang-staging
```

### 3.2 生产环境部署

```bash
# 部署到 production
helm upgrade --install wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --set global.imageTag=$(git rev-parse --short HEAD) \
  --namespace wanxiang-production \
  --wait --timeout 15m

# 验证所有 Pod 就绪
kubectl get pods -n wanxiang-production -w

# 验证服务
kubectl get svc -n wanxiang-production
kubectl get hpa -n wanxiang-production
kubectl get ingress -n wanxiang-production
```

### 3.3 金丝雀发布

```bash
# 10% 流量到新版本
helm upgrade wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --set global.imageTag=$(git rev-parse --short HEAD) \
  --set apiServer.canary.enabled=true \
  --set apiServer.canary.weight=10 \
  --namespace wanxiang-production

# 确认无异常后，全量发布
helm upgrade wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --set global.imageTag=$(git rev-parse --short HEAD) \
  --set apiServer.canary.weight=100 \
  --namespace wanxiang-production
```

### 3.4 卸载

```bash
helm uninstall wanxiang --namespace wanxiang-production
kubectl delete namespace wanxiang-production
```

---

## 4. 服务清单

| # | 服务 | 端口 | 生产 Pod 数 | CPU | 内存 | HPA | PDB |
|---|------|------|------------|-----|------|-----|-----|
| 1 | api-server | 8000 | 3 | 1-2 | 2-4G | 3-20 | minAvailable: 2 |
| 2 | gateway | 8001 | 3 | 0.5-1 | 1-2G | — | — |
| 3 | nlu-service | 8002 | 2 | 0.5-1 | 1-2G | — | — |
| 4 | model-router | 8003 | 2 | 0.5-1 | 1-2G | — | — |
| 5 | agent-orchestrator | 8004 | 3 | 1-2 | 2-4G | 3-10 | — |
| 6 | rag-service | 8005 | 2 | 1-2 | 2-4G | — | — |
| 7 | embedding-service | 8006 | 2 | 2-4 | 4-8G | 2-8 | — |
| 8 | sd-service | 8007 | 2 | 1-2 | 4-8G | — | — |
| 9 | tool-sandbox | 8008 | 5 | 0.5-1 | 1-2G | 5-20 | — |
| 10 | skill-runtime | 8009 | 3 | 0.5-1 | 1-2G | — | — |
| 11 | prometheus | 9090 | 1 | 1-2 | 2-4G | — | — |
| 12 | grafana | 3000 | 1 | 0.25-0.5 | 0.5-1G | — | — |
| 13 | otel-collector | 4317 | 1 | 0.5-1 | 1-2G | — | — |
| 14 | jaeger | 16686 | 1 | 0.5-1 | 1-2G | — | — |

---

## 5. 扩缩容

### 5.1 手动扩缩容

```bash
# 手动调整副本数
kubectl scale deployment wanxiang-api-server --replicas=5 -n wanxiang-production

# 修改 HPA 参数
kubectl patch hpa wanxiang-api-server -n wanxiang-production --type merge -p '{
  "spec": {
    "maxReplicas": 30,
    "metrics": [{
      "type": "Resource",
      "resource": {
        "name": "cpu",
        "target": { "type": "Utilization", "averageUtilization": 60 }
      }
    }]
  }
}'
```

### 5.2 通过 Helm values 扩缩容

```bash
# 临时修改副本数
helm upgrade wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --set apiServer.replicaCount=5 \
  --set toolSandbox.hpa.maxReplicas=30 \
  --namespace wanxiang-production
```

### 5.3 节点扩容

```bash
# 添加 Worker 节点到 K3s 集群
curl -sfL https://get.k3s.io | K3S_URL=https://master-ip:6443 K3S_TOKEN=<token> sh -

# 为 GPU 节点打标签
kubectl label node <node-name> gpu=true

# 验证节点就绪
kubectl get nodes -l gpu=true
```

---

## 6. 备份恢复

### 6.1 备份策略

| 数据 | 备份频率 | 备份方式 | 保留期 |
|------|---------|---------|--------|
| PostgreSQL | 每小时 | WAL + pg_dump | 7天热 / 1年冷 |
| Redis | 每6小时 | RDB 快照 | 7天 |
| Qdrant 向量 | 每天 | Snapshot + S3 | 30天 |
| Elasticsearch | 每天 | Snapshot + S3 | 30天 |
| MinIO 文件 | 每天 | 跨区域复制 | 90天 |
| K8s 资源清单 | 变更时实时 | GitOps (ArgoCD) | 永久 |

**RPO: < 1小时 | RTO: < 30分钟**

### 6.2 PostgreSQL 备份

```bash
# 手动备份
kubectl exec -n wanxiang-production <postgres-pod> -- pg_dump -U wanxiang wanxiang_ai | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# 从备份恢复
gunzip < backup_20260621_120000.sql.gz | kubectl exec -i -n wanxiang-production <postgres-pod> -- psql -U wanxiang wanxiang_ai
```

### 6.3 Helm Release 备份

```bash
# 导出 Helm release
helm get values wanxiang -n wanxiang-production > wanxiang-production-values-backup.yaml
helm get manifest wanxiang -n wanxiang-production > wanxiang-production-manifest-backup.yaml

# 从备份恢复
helm upgrade --install wanxiang ./deploy \
  -f wanxiang-production-values-backup.yaml \
  --namespace wanxiang-production
```

### 6.4 灾难恢复流程

1. **单 Pod 宕机** → K8s 自动重启 + PDB 保护
2. **单节点宕机** → Pod 自动迁移到其他节点
3. **PG 主节点故障** → Patroni 自动 Failover
4. **Redis 节点故障** → Cluster 自动故障转移
5. **整集群故障** → 跨区域冷备 + DNS 切换（RTO < 30min）

**恢复演练**: 每月 1 次，记录恢复时间 + 验证数据完整性

---

## 7. 故障排查

### 7.1 Pod 状态异常

```bash
# 查看所有 Pod 状态
kubectl get pods -n wanxiang-production -o wide

# 查看 Pod 详情（事件、错误信息）
kubectl describe pod <pod-name> -n wanxiang-production

# 查看 Pod 日志
kubectl logs <pod-name> -n wanxiang-production
kubectl logs <pod-name> -n wanxiang-production --previous  # 崩溃前的日志
kubectl logs <pod-name> -n wanxiang-production -f          # 实时跟踪

# 查看多个容器的日志
kubectl logs <pod-name> -n wanxiang-production --all-containers
```

### 7.2 服务不可达

```bash
# 检查 Service 端点
kubectl get endpoints -n wanxiang-production

# 检查 Ingress
kubectl get ingress -n wanxiang-production
kubectl describe ingress <ingress-name> -n wanxiang-production

# 从集群内部测试连通性
kubectl run debug --image=busybox -it --rm --restart=Never -- \
  wget -qO- http://wanxiang-api-server:8000/health

# 检查 NetworkPolicy
kubectl get networkpolicy -n wanxiang-production
kubectl describe networkpolicy <policy-name> -n wanxiang-production
```

### 7.3 HPA 不生效

```bash
# 查看 HPA 状态
kubectl get hpa -n wanxiang-production
kubectl describe hpa <hpa-name> -n wanxiang-production

# 常见原因:
# 1. 缺少 resources.requests.cpu
# 2. metrics-server 未安装
# 3. Pod 数量已达 minReplicas 或 maxReplicas
# 4. CPU 使用率未超过 targetCPUUtilization

# 安装 metrics-server（K3s 通常已内置）
kubectl top pods -n wanxiang-production
```

### 7.4 GPU Pod 调度失败

```bash
# 检查 GPU 资源
kubectl describe node <gpu-node> | grep -A5 "Allocated resources"

# 检查 GPU 节点标签
kubectl get nodes --show-labels | grep gpu

# 检查 tolerations 和 nodeSelector
kubectl get pod <pod-name> -n wanxiang-production -o jsonpath='{.spec.tolerations}'
kubectl get pod <pod-name> -n wanxiang-production -o jsonpath='{.spec.nodeSelector}'
```

### 7.5 OOMKilled

```bash
# 查看是否 OOMKilled
kubectl get pod <pod-name> -n wanxiang-production -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'

# 调整内存限制
helm upgrade wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --set apiServer.resources.limits.memory=8Gi \
  --namespace wanxiang-production
```

### 7.6 Helm 回滚

```bash
# 查看 Helm 历史
helm history wanxiang -n wanxiang-production

# 回滚到上一版本
helm rollback wanxiang -n wanxiang-production

# 回滚到指定版本
helm rollback wanxiang <revision-number> -n wanxiang-production
```

---

## 8. 配置说明

### 8.1 文件结构

```
deploy/
├── Chart.yaml                         # Helm Chart 元数据
├── values.yaml                        # 默认配置（开发环境）
├── values-production.yaml             # 生产环境覆盖配置
├── values-staging.yaml                # 测试环境覆盖配置
├── alerting-rules.yaml                # Prometheus 告警规则
├── docker-compose-dev.yaml            # 开发环境 Docker Compose
├── README.md                          # 本文档
└── templates/
    ├── _helpers.tpl                   # 模板辅助函数
    ├── namespace.yaml                 # 命名空间定义
    ├── api-server-deployment.yaml     # API Server (Deployment + Service + HPA + PDB)
    ├── gateway-deployment.yaml        # Gateway (Deployment + Service)
    ├── agent-orchestrator-deployment.yaml  # 编排器 (Deployment + Service + HPA)
    ├── rag-service-deployment.yaml    # RAG 服务 (Deployment + Service)
    ├── tool-sandbox-deployment.yaml   # 工具沙箱 (Deployment + HPA)
    ├── ingress.yaml                   # Traefik IngressRoute + Middleware
    ├── networkpolicy.yaml             # 网络策略（服务间隔离）
    ├── configmap-global.yaml          # 全局配置 ConfigMap
    └── observability.yaml             # Prometheus + Grafana + OTEL + Jaeger
```

### 8.2 常用 Helm 命令

```bash
# 查看已部署的 release
helm list -n wanxiang-production

# 查看 release 配置
helm get values wanxiang -n wanxiang-production

# 模板渲染（不部署）
helm template wanxiang ./deploy -f ./deploy/values-production.yaml -n wanxiang-production

# 验证配置
helm lint ./deploy -f ./deploy/values-production.yaml

# 干运行
helm upgrade --install wanxiang ./deploy \
  -f ./deploy/values-production.yaml \
  --namespace wanxiang-production \
  --dry-run --debug
```

### 8.3 环境变量覆盖

```bash
# 覆盖镜像标签
--set global.imageTag=v1.2.3

# 覆盖镜像仓库
--set global.imageRegistry=registry-staging.wanxiang.ai

# 覆盖数据库连接（通过 Secret）
--set apiServer.env[0].valueFrom.secretKeyRef.name=wanxiang-secrets-staging
```

---

## 联系方式

- **DevOps 团队**: devops@wanxiang.ai
- **应急值班**: oncall@wanxiang.ai
- **运维 Wiki**: https://wiki.wanxiang.ai/runbooks
- **监控大盘**: https://grafana.wanxiang.ai
- **链路追踪**: https://jaeger.wanxiang.ai
