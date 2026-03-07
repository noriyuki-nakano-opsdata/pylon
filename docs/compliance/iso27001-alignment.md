# ISO 27001:2022 Annex A Control Alignment

This document maps Pylon's controls to key ISO 27001:2022 Annex A requirements.

## A.5 - Information Security Policies

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.5.1 - Policies for information security | Policy pack system | Declarative, versioned security policies enforced at runtime |
| A.5.2 - Review of policies | Policy versioning + CI | Policies reviewed through PR workflow with required approvals |
| A.5.3 - Segregation of duties | RBAC + autonomy ladder | Enforced separation between policy authors and approvers |

## A.6 - Organization of Information Security

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.6.1 - Internal organization | Tenant isolation model | Each tenant operates in isolated namespace with dedicated resources |
| A.6.2 - Mobile / remote access | OAuth 2.1 + SPIFFE | Workload identity verification regardless of network location |

## A.8 - Asset Management

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.8.1 - Responsibility for assets | Resource registry | All resources tracked with ownership metadata |
| A.8.2 - Information classification | Policy labels | Classification labels on resources driving policy enforcement |
| A.8.3 - Media handling | Persistent volume encryption | Encrypted storage for all persistent data |

## A.9 - Access Control

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.9.1 - Business requirements | RBAC policies | Role definitions aligned to business functions |
| A.9.2 - User access management | OAuth 2.1 flows | Standards-based authentication with MFA support |
| A.9.3 - User responsibilities | Autonomy ladder | Progressive trust with explicit acknowledgment at each level |
| A.9.4 - System access control | Network policies + SPIRE | Kubernetes network policies with mutual TLS via SPIFFE/SPIRE |

## A.12 - Operations Security

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.12.1 - Operational procedures | GitOps workflows | All operational changes through documented, reviewed pipelines |
| A.12.2 - Protection from malware | Sandbox isolation | gVisor/Kata container runtime with restricted syscalls |
| A.12.3 - Backup | Volume snapshots + DR | Automated backup schedules with documented restore procedures |
| A.12.4 - Logging and monitoring | Prometheus + Loki stack | Centralized logging with structured audit events |
| A.12.5 - Control of operational software | SLSA Level 3 builds | Provenance attestation for all production artifacts |
| A.12.6 - Vulnerability management | VEX + pip-audit | Weekly automated vulnerability scanning with OpenVEX output |

## A.14 - System Acquisition, Development and Maintenance

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.14.1 - Security requirements | ADR process | Security requirements documented as Architecture Decision Records |
| A.14.2 - Development security | TDD + code review | Mandatory tests and peer review for all changes |
| A.14.3 - Test data | Isolated test environments | Dedicated test namespaces with synthetic data |

## A.17 - Business Continuity

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.17.1 - Continuity planning | DR documentation | Documented recovery procedures with RTO/RPO targets |
| A.17.2 - Redundancy | HPA + PDB | Horizontal scaling with pod disruption budgets |

## A.18 - Compliance

| Control | Pylon Mapping | Evidence |
|---------|---------------|----------|
| A.18.1 - Legal requirements | License scanning (SBOM) | SPDX SBOM generation with license identification |
| A.18.2 - Security reviews | SLSA provenance | Cryptographic build provenance for audit trail |
