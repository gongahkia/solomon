<!-- SPDX-License-Identifier: Apache-2.0 -->

# Ingestion with boundary review

```mermaid
sequenceDiagram
    participant U as Curator or API client
    participant S as Solomon service
    participant B as Solomon boundary
    participant E as Event store
    participant G as Dependency graph
    participant A as Audit journal

    U->>S: ingest(content, provenance, scope)
    S->>B: inspect content and policy
    alt boundary passes
        B-->>S: sanitized/reviewed payload
        S->>E: append knowledge event
        E-->>S: durable KnowledgeItem
        S->>G: extract or queue dependency suggestions
        S->>A: append ingestion metadata
        S-->>U: item + review evidence
    else boundary rejects
        B-->>S: fail-closed decision
        S->>A: append rejected-ingestion metadata
        S-->>U: structured rejection; no item stored
    end
```
