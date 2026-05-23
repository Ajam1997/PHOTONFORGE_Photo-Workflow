# Architecture

## 3. Requirements

### 3.1 Functional Requirements

| ID | Description | Implementation |
|:---|:---|:---|
| FR-1.1 | Automated Media Ingest | udev-triggered rsync |
| FR-1.2 | Spatio-Temporal Grouping | Cluster if delta < 500ms |

### 3.2 Non-Functional Requirements

| ID | Description | Specification |
|:---|:---|:---|
| NFR-2.1 | Internet Independence | 100% offline at runtime. |
| NFR-2.2 | Resource Efficiency | RSS <= 1.5 GB. |

### 3.3 Key Performance Measures

| KPM | Metric | Target | Owner | Verified By |
|:---|:---|:---|:---|:---|
| KPM-1.1 | Ingest Latency | >= 80% USB 3.0 bandwidth | @devops | @verification |
| KPM-1.2 | Inference Speed | <= 2.5s per image | @engineer | @verification |
