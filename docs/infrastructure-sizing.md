# Infrastructure Sizing Guide

Recommended infrastructure profiles for Pylon deployments.

## Small Profile (Dev / Test)

**Use case**: Development, CI/CD, proof-of-concept

| Resource | Specification |
|----------|---------------|
| Kubernetes nodes | 1-2 nodes |
| CPU per node | 4 vCPU |
| Memory per node | 16 GiB |
| Storage | 100 GiB SSD |
| GPU | None |
| Max tenants | 1-3 |
| Max concurrent agents | 5 |

**Estimated cloud cost**: $200-400/month (AWS m6i.xlarge or equivalent)

### Services
- PostgreSQL: single replica, 10 GiB storage
- Redis: single instance, 1 GiB memory
- RabbitMQ: single node, default limits
- MinIO: single node, 50 GiB

---

## Medium Profile (Staging)

**Use case**: Staging, integration testing, small production

| Resource | Specification |
|----------|---------------|
| Kubernetes nodes | 3-5 nodes |
| CPU per node | 8 vCPU |
| Memory per node | 32 GiB |
| Storage | 500 GiB SSD |
| GPU | 1x T4 (optional) |
| Max tenants | 5-10 |
| Max concurrent agents | 20 |

**Estimated cloud cost**: $1,200-2,000/month (AWS m6i.2xlarge or equivalent)

### Services
- PostgreSQL: primary + 1 replica, 50 GiB storage, pgvector enabled
- Redis: primary + replica, 4 GiB memory
- RabbitMQ: 3-node cluster with quorum queues
- MinIO: distributed mode, 200 GiB
- Prometheus + Grafana: dedicated node

---

## Large Profile (Production)

**Use case**: Multi-tenant production, high availability

| Resource | Specification |
|----------|---------------|
| Kubernetes nodes | 6-12 nodes (3+ AZs) |
| CPU per node | 16 vCPU |
| Memory per node | 64 GiB |
| Storage | 2 TiB SSD (provisioned IOPS) |
| GPU | 2-4x A10G or L4 |
| Max tenants | 50+ |
| Max concurrent agents | 100+ |

**Estimated cloud cost**: $5,000-12,000/month (AWS m6i.4xlarge or equivalent)

### Services
- PostgreSQL: HA cluster (primary + 2 replicas), 500 GiB, pgvector + HNSW
- Redis: Sentinel or cluster mode, 16 GiB memory
- RabbitMQ: 3-node cluster, quorum queues, federation for multi-region
- MinIO: distributed across AZs, 1 TiB
- Prometheus + Grafana + Loki: dedicated monitoring stack
- Vault: HA with auto-unseal
- Harbor: HA with S3 backend storage

---

## Capacity Planning

### Scaling Triggers

| Metric | Threshold | Action |
|--------|-----------|--------|
| CPU utilization | > 70% sustained | Add worker nodes |
| Memory utilization | > 80% sustained | Add worker nodes or increase node size |
| PostgreSQL connections | > 80% max | Increase max_connections or add read replicas |
| Queue depth (RabbitMQ) | > 1000 messages sustained | Scale agent workers |
| Storage utilization | > 75% | Expand volumes or add retention policies |
| Agent startup latency | > 30s p95 | Pre-warm agent pool or add GPU nodes |

### Resource Requests per Component

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit |
|-----------|-------------|----------------|-----------|--------------|
| Pylon Gateway | 500m | 512Mi | 2000m | 2Gi |
| Agent (headless) | 500m | 1Gi | 2000m | 4Gi |
| Agent (GPU) | 1000m | 4Gi | 4000m | 16Gi |
| Policy Engine | 250m | 256Mi | 1000m | 1Gi |
| PostgreSQL | 500m | 1Gi | 2000m | 4Gi |
| Redis | 250m | 512Mi | 1000m | 2Gi |
| RabbitMQ | 500m | 512Mi | 1000m | 2Gi |

### Tenant Overhead

Each additional tenant adds approximately:
- **Namespace resources**: ~100Mi base memory for network policies, service accounts, RBAC
- **Database**: ~50 MiB per tenant schema (grows with usage)
- **RabbitMQ**: 4 queues per tenant (high, normal, batch, DLQ)
- **Vault**: 1 policy + 1 role per tenant
