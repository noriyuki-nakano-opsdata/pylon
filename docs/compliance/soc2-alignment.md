# SOC 2 Trust Service Criteria Alignment

This document maps Pylon's security controls and architecture to the AICPA SOC 2 Trust Service Criteria.

## CC1 - Control Environment

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC1.1 - Commitment to integrity | CODEOWNERS enforcement | Repository-level ownership with required reviews |
| CC1.2 - Board oversight | Governance policy packs | Declarative policy definitions in version control |
| CC1.3 - Authority and responsibility | RBAC with autonomy ladder | Role-based permissions with escalating trust levels |
| CC1.4 - Competence | Approval gates | Multi-stage approval workflows for sensitive operations |

## CC2 - Communication and Information

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC2.1 - Internal communication | Structured audit logs | All policy decisions logged with full context |
| CC2.2 - External communication | Webhook notifications | Real-time alerts for policy violations and approvals |
| CC2.3 - Relevant information | Decision audit trail | HMAC-chained event log for tamper evidence |

## CC3 - Risk Assessment

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC3.1 - Risk objectives | Threat modeling | Architecture-level threat analysis per ADR |
| CC3.2 - Risk identification | Policy engine rules | Automated detection of risky patterns and configurations |
| CC3.3 - Fraud consideration | HMAC chain verification | Cryptographic integrity verification of decision history |
| CC3.4 - Change impact | Diff analysis | Automated risk scoring of proposed changes |

## CC5 - Control Activities

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC5.1 - Risk mitigation | RBAC enforcement | Role-based access control at every decision point |
| CC5.2 - Technology controls | Sandbox isolation | gVisor/Kata-based execution sandboxing |
| CC5.3 - Policy deployment | Policy pack system | Versioned, auditable policy deployment pipeline |

## CC6 - Logical and Physical Access Controls

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC6.1 - Access control | OAuth 2.1 + SPIFFE/SPIRE | Standards-based identity with workload attestation |
| CC6.2 - Credential management | Vault integration | Dynamic secrets with automatic rotation |
| CC6.3 - Access modification | Autonomy ladder | Progressive trust escalation with explicit approval |
| CC6.6 - Tenant isolation | Namespace separation | Kubernetes namespace + network policy isolation |

## CC7 - System Operations

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC7.1 - Infrastructure monitoring | Prometheus + Grafana | Full-stack observability with custom dashboards |
| CC7.2 - Anomaly detection | Alerting rules | Threshold and anomaly-based alerting |
| CC7.3 - Change evaluation | CI/CD pipeline | Automated testing, linting, and security scanning |
| CC7.4 - Incident response | DR strategy | Documented recovery procedures with RTO/RPO targets |

## CC8 - Change Management

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| CC8.1 - Change authorization | PR approval workflow | Required reviews with CODEOWNERS enforcement |
| CC8.2 - Infrastructure changes | GitOps pipeline | All infrastructure changes through version control |
| CC8.3 - Configuration management | Helm charts + ArgoCD | Declarative configuration with drift detection |

## A1 - Availability

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| A1.1 - Capacity management | HPA + resource quotas | Automatic scaling with resource limits per tenant |
| A1.2 - Recovery objectives | PDB + DR procedures | Pod disruption budgets, documented RTO < 4h / RPO < 1h |
| A1.3 - Backup and recovery | Persistent volume snapshots | Scheduled backups with tested restore procedures |

## PI1 - Processing Integrity

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| PI1.1 - Processing accuracy | HMAC hash chains | Cryptographic verification of decision sequence integrity |
| PI1.2 - Completeness | Replay verification | Ability to replay and verify complete decision history |
| PI1.3 - Timeliness | Event timestamps | UTC timestamps on all events with NTP synchronization |

## C1 - Confidentiality

| Criteria | Pylon Control | Implementation |
|----------|---------------|----------------|
| C1.1 - Confidential information | Secret scrubbing | Automatic detection and redaction of sensitive data |
| C1.2 - Disposal | TTL-based expiration | Automatic secret and session data expiration |
| C1.3 - Confidentiality commitments | Vault encryption | Transit encryption for secrets at rest and in motion |
