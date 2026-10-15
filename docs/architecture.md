# HealthLake architecture

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

Six diagrams plus the entity-relationship diagram. All are Mermaid, so GitHub renders them. The overview is in the
[README](../README.md#architecture). Decisions behind these choices are in [ADRs](../architecture/adr/).

## 1. Batch lifecycle (one processing)
A **batch** is the immutable delivery (identified by the SHA-256 of its manifest). A **processing** is that batch
processed by one version of the code, mappings and validation rules. An **attempt** is one try of a processing;
several attempts may run, one at a time (advisory lock).

```mermaid
stateDiagram-v2
  [*] --> registered: discover (manifest parsed)
  registered --> verified: verify (sizes + SHA-256)
  registered --> invalid: hash or size mismatch
  verified --> archived: archive to RawStore
  state processing {
    [*] --> pending
    pending --> p_archived: archive
    p_archived --> adapted: adapt (CSV/JSON -> FHIR R4)
    adapted --> validated: validate + resolve + classify
    adapted --> blocked: processing gate fails
    validated --> normalized: normalize
    normalized --> loaded: load Silver (one transaction)
    p_archived --> failed: unexpected error
  }
  archived --> processing
  loaded --> [*]
  blocked --> [*]
```

Exit codes from every CLI step: 0 ok, 1 unexpected, 2 contract, 3 quality, 4 transient, 5 conflict. Airflow does
not retry 2, 3 or 5. It retries 1 and 4 twice with exponential backoff.

## 2. Occurrence outcomes and the processing gate
Every resource occurrence received gets exactly one outcome, in this priority order. The counts reconcile:
`received = accepted + out_of_scope + deduplicated + rejected`.

```mermaid
flowchart TD
  O["Resource occurrence<br/>(bronze.resource_occurrence)"] --> V{"Structural validation<br/>val-1"}
  V -->|error/fatal| REJ["rejected"]
  V -->|ok| R{"References resolved?<br/>(same source namespace)"}
  R -->|required ref missing| REJ
  R -->|ok| D{"Same entity already seen<br/>in this batch?"}
  D -->|same content| DED["deduplicated"]
  D -->|different content| REJ
  D -->|no| S{"In analytic scope?"}
  S -->|"resource type not modelled"| OOS["out_of_scope<br/>(kept in Silver, not in Gold)"]
  S -->|yes| ACC["accepted"]
  REJ & DED & OOS & ACC --> G{"Processing gate"}
  G -->|"fatal issue, identity or content conflict,<br/>invalid update, reject rate of new resources > 1 %,<br/>reconciliation mismatch"| BL["processing blocked<br/>nothing loaded"]
  G -->|otherwise| LD["load accepted + out_of_scope<br/>rejected stay in quarantine"]
```

## 3. Release lifecycle
```mermaid
sequenceDiagram
  participant CLI as healthlake CLI
  participant PG as PostgreSQL
  participant DBT as dbt (role hl_dbt)
  CLI->>PG: build-snapshot: release_id = hash(processings, code, dbt fingerprint)
  CLI->>PG: create schema release_<16 hex> (status building)
  CLI->>DBT: dbt build --target candidate schema (models + 100 tests + indexes)
  DBT-->>PG: tables in candidate schema (status built)
  CLI->>PG: quality-gate as publish role (dbt results + release checks)
  alt gate passed
    CLI->>PG: one transaction: active_release := release_id (status published)
    CLI->>PG: purge releases beyond retention (never the active one)
  else gate failed
    CLI->>PG: status gate_failed, active release unchanged
  end
```
Rebuilding the same inputs produces the same `release_id`, so the command is a no-op the second time.

## 4. Airflow DAGs
```mermaid
flowchart LR
  subgraph D["healthlake_discovery (every 5 min, max 1 active run)"]
    disc["discover"] --> trig["trigger_ingestion<br/>(mapped, one per pending batch,<br/>run_id batch__&lt;batch_id&gt;)"]
  end
  subgraph I["healthlake_ingestion (one run per batch)"]
    sa["start_attempt"] --> ve["verify"] --> ar["archive"] --> ad["adapt"] --> va["validate"] --> rr["resolve_references"]
    rr --> cq["classify_quality"] --> no["normalize"] --> ls["load_silver"] --> bs["build_snapshot"]
    bs --> db["dbt_build"] --> dd["dbt_docs"] --> qg["quality_gate"] --> pu["publish"] --> fr["final_report<br/>(ALL_DONE, only leaf)"]
  end
  trig -.-> sa
```
Ingestion tasks use the `healthlake_ingestion` pool and release tasks the `healthlake_publication` pool, one
slot each, so batches are processed one at a time and two releases never build at the same time. `final_report` always runs. It fails the DAG run unless the
attempt succeeded and its release is published, so a blocked batch shows as a failed run.

## 5. Deployment (Docker Compose)
```mermaid
flowchart TB
  subgraph host["Host (ports bound to 127.0.0.1)"]
    subgraph data_net
      PG[("postgres 17<br/>healthlake + airflow DBs")]
      INIT["db-init / airflow-init<br/>(one-shot)"]
      AS["airflow-api-server :8080"]
      SC["airflow-scheduler<br/>LocalExecutor"]
      DP["airflow-dag-processor"]
      API["api :8000"]
    end
    subgraph app_net
      API
      DASH["dashboard :8501"]
    end
    SEC[".secrets/ -> /run/secrets"]
    VOL[("volumes: pg_data, landing, lake,<br/>work, artifacts, airflow_logs")]
  end
  SC -->|healthlake CLI| PG
  API -->|read-only role| PG
  DASH -->|HTTP + API key| API
  SEC -.-> PG & API & DASH & SC
```
The dashboard has no network path to PostgreSQL. The `cli` and `synthea` services sit behind the `tools`
profile and run only on demand.

## 6. Identifiers
```mermaid
flowchart LR
  M["manifest (canonical JSON)"] -->|sha256| BID["batch_id"]
  BID --> PID["processing_id = sha256(batch_id, code, mapping, validation versions)"]
  PID --> AID["attempt_id = UUIDv4 (per try)"]
  NS["source namespace UUID"] --> EID["entity_id = UUIDv5(namespace, Type/id)"]
  EID --> RVID["resource_version_id = sha256(entity_id, resource sha256, mapping version)"]
  PID --> RID["release_id = sha256(sorted processing_ids, code version, dbt fingerprint)"]
```
Canonical JSON here means sorted keys, compact separators and UTF-8. It is a HealthLake convention, not RFC 8785
(JCS). See [data-contract.md](data-contract.md).

## 7. Entity-relationship diagram (control, Bronze, Silver, quality)
Gold tables are documented in [data-dictionary.md](data-dictionary.md). Typed Silver tables (`observation`,
`condition`, `medication_request`, `organization`, `practitioner`, `observation_component`,
`encounter_participant`) follow the same pattern as `patient` and `encounter`: one row per resource version.

```mermaid
erDiagram
  CTL_SOURCE ||--o{ CTL_BATCH : delivers
  CTL_BATCH ||--o{ CTL_PROCESSING : "processed as"
  CTL_PROCESSING ||--o{ CTL_ATTEMPT : "tried by"
  CTL_BATCH ||--o{ BRONZE_BATCH_FILE : lists
  BRONZE_FILE ||--o{ BRONZE_BATCH_FILE : "stored once"
  CTL_PROCESSING ||--o{ BRONZE_RESOURCE_OCCURRENCE : receives
  BRONZE_RESOURCE_OCCURRENCE ||--o{ SILVER_RESOURCE_LINEAGE : "traced by"
  SILVER_RESOURCE_VERSION ||--o{ SILVER_RESOURCE_LINEAGE : "comes from"
  CTL_PROCESSING ||--o{ SILVER_PROCESSING_RESOURCE : "sees entity at"
  SILVER_RESOURCE_VERSION ||--o{ SILVER_PROCESSING_RESOURCE : version
  SILVER_RESOURCE_VERSION ||--o{ SILVER_REFERENCE : "points to"
  SILVER_RESOURCE_VERSION ||--o{ SILVER_IDENTIFIER : has
  SILVER_RESOURCE_VERSION ||--o{ SILVER_CODING : has
  SILVER_RESOURCE_VERSION ||--o| SILVER_PATIENT : typed
  SILVER_RESOURCE_VERSION ||--o| SILVER_ENCOUNTER : typed
  CTL_RELEASE ||--o{ CTL_RELEASE_PROCESSING : includes
  CTL_PROCESSING ||--o{ CTL_RELEASE_PROCESSING : "included in"
  CTL_RELEASE ||--o{ SILVER_SNAPSHOT_MEMBER : freezes
  CTL_ACTIVE_RELEASE |o--|| CTL_RELEASE : points
  CTL_PROCESSING ||--o{ QUALITY_ISSUE : raises
  QUALITY_ISSUE |o--o{ QUALITY_ISSUE : "caused by"

  CTL_SOURCE { text source_id PK
    text source_format
    uuid namespace_uuid }
  CTL_BATCH { text batch_id PK
    text source_id FK
    bigint source_revision
    jsonb manifest
    text status }
  CTL_PROCESSING { text processing_id PK
    text batch_id FK
    text code_version
    text status
    jsonb counters }
  CTL_ATTEMPT { uuid attempt_id PK
    text processing_id FK
    text status
    text current_step }
  BRONZE_FILE { text sha256 PK
    bigint size_bytes
    text storage_key }
  BRONZE_BATCH_FILE { text batch_id FK
    text relative_path }
  BRONZE_RESOURCE_OCCURRENCE { text processing_id FK
    int occurrence_no
    text locator
    text outcome }
  SILVER_RESOURCE_VERSION { text resource_version_id PK
    uuid entity_id
    text resource_type
    jsonb resource
    bool in_analytic_scope }
  SILVER_RESOURCE_LINEAGE { text resource_version_id FK
    text processing_id FK
    int occurrence_no }
  SILVER_PROCESSING_RESOURCE { text processing_id FK
    uuid entity_id
    text resource_version_id FK
    bigint source_revision }
  SILVER_REFERENCE { text resource_version_id FK
    text path
    text resolution_method
    uuid target_entity_id }
  SILVER_IDENTIFIER { text resource_version_id FK
    text source_id
    text system
    text value }
  SILVER_CODING { text resource_version_id FK
    text path
    text system
    text code }
  SILVER_PATIENT { text resource_version_id PK
    uuid entity_id
    text gender
    date birth_date }
  SILVER_ENCOUNTER { text resource_version_id PK
    uuid entity_id
    uuid patient_entity_id
    timestamptz period_start }
  CTL_RELEASE { text release_id PK
    text schema_name
    text status
    jsonb gate_result }
  CTL_RELEASE_PROCESSING { text release_id FK
    text processing_id FK }
  SILVER_SNAPSHOT_MEMBER { text snapshot_id "= release_id"
    uuid entity_id
    text resource_version_id }
  CTL_ACTIVE_RELEASE { bool singleton PK
    text release_id FK }
  QUALITY_ISSUE { bigint issue_id PK
    text processing_id FK
    text check_id
    text severity
    bigint caused_by_issue_id FK }
```
