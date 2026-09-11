# ERD — Data Model & Managed Database

Physical schema, cardinalities and unique constraints, exactly as implemented in
[`models.py`](models.py) / [`alembic/versions/0001_initial_schema.py`](alembic/versions/0001_initial_schema.py).
Posted per work-pack §2.3 ("draw the ERD before writing a model... post it in the channel on
day three"). Lives here rather than `docs/erd.png` because `/docs/` is Nisarg's directory
(`CODEOWNERS`) and a rendered PNG can't be diffed in review the way this can.

```mermaid
erDiagram
    CARRIERS ||--o{ FLIGHTS : operates
    AIRPORTS ||--o{ FLIGHTS : "origin of"
    AIRPORTS ||--o{ FLIGHTS : "destination of"
    AIRCRAFT |o--o{ FLIGHTS : "tail number of"
    USERS ||--o{ DOCUMENTS : uploads
    USERS ||--o{ DISPOSITIONS : files
    USERS |o--o{ REPORTS : "assigned to"
    DOCUMENTS ||--o{ REPORTS : contains
    REPORTS ||--o{ REPORT_FIELDS : "flattens to"
    REPORTS ||--o{ REPORT_HAZARDS : "classified as"
    HAZARD_CATEGORIES ||--o{ REPORT_HAZARDS : labels
    REPORTS ||--o{ REPORT_FLIGHT_LINKS : "linked to"
    FLIGHTS ||--o{ REPORT_FLIGHT_LINKS : "linked from"
    REPORTS ||--o{ DISPOSITIONS : "triaged via"
    DOCUMENTS ||--o{ INGEST_EVENTS : logs

    CARRIERS {
        int dot_id PK "BTS natural key, no sequence"
        string iata_code
        string name
    }
    AIRPORTS {
        int airport_id PK "BTS natural key, no sequence"
        string iata_code
        string city_name
        string state
    }
    AIRCRAFT {
        string tail_number PK
        date first_seen
        date last_seen
    }
    FLIGHTS {
        bigint id PK
        date flight_date
        string reporting_airline
        int dot_id FK
        int flight_number
        string tail_number FK "nullable"
        int origin_airport_id FK
        int dest_airport_id FK
        time crs_dep_time
        time dep_time
        bool cancelled
        string cancellation_code "A/B/C/D or null"
        bool diverted
        int distance
    }
    USERS {
        bigint id PK
        citext email UK
        string password_hash
        string role "analyst/manager/admin"
    }
    DOCUMENTS {
        bigint id PK
        string sha256 UK "idempotency key #1"
        string s3_bucket
        string s3_key
        bigint uploaded_by FK
        string status "received/queued/parsing/parsed/failed"
        int attempts
    }
    REPORTS {
        bigint id PK
        bigint document_id FK
        string acn UK "idempotency key #2"
        date report_date
        text narrative
        tsvector narrative_tsv "GENERATED, GIN indexed"
        jsonb coded "GIN jsonb_path_ops indexed"
        int priority "denormalised, see priority.py"
        string state "new/triaged/escalated/closed"
        bigint assigned_to FK "nullable"
        bool manager_flagged
    }
    REPORT_FIELDS {
        bigint report_id PK_FK
        string path PK "verbatim NASA dotted path"
        string value PK
    }
    HAZARD_CATEGORIES {
        int id PK
        string code UK
        string label
        numeric severity_weight "data, not a magic number"
    }
    REPORT_HAZARDS {
        bigint report_id PK_FK
        int category_id PK_FK
        string source PK "nasa (ground truth) or model (prediction)"
        numeric confidence
    }
    REPORT_FLIGHT_LINKS {
        bigint report_id PK_FK
        bigint flight_id PK_FK
        numeric confidence
        string method
    }
    DISPOSITIONS {
        bigint id PK
        bigint report_id FK
        bigint analyst_id FK
        string state
        timestamptz created_at
    }
    INGEST_EVENTS {
        bigint id PK
        bigint document_id FK
        string event
        timestamptz at
        jsonb detail
    }
```

## Reading this diagram

**Two idempotency keys carry the whole "processed twice is one row" story:**
`documents.sha256` and `reports.acn`. Nothing else in the write path needs to be clever
about duplicates — `db/repo.py::SqlRepo.create_document` is `INSERT ... ON CONFLICT DO
NOTHING RETURNING`, one round trip.

**`carriers.dot_id` and `airports.airport_id` are natural keys, not surrogates** — BTS's own
identifiers, always supplied by the loader, `autoincrement=False`. A flight row references
them directly; there is no synthetic id standing between `flights` and the reference tables
the way there is for everything else.

**`report_hazards.source` is the whole scoring mechanism for Smit's accuracy number.**
`'nasa'` rows are NASA's own `Anomaly.*` codes (ground truth); `'model'` rows are the
classifier's prediction. Both live in the same table, keyed the same way, so comparing them
is a self-join, not a cross-system merge.

**`reports.priority` is denormalised on purpose.** See [`priority.py`](priority.py)'s
docstring for why it can't be a Postgres `GENERATED` column (the recency term depends on
`CURRENT_DATE`, which Postgres correctly refuses to call immutable) and how it's kept in
sync with `services/api/ranking.py` instead. `ix_reports_priority_keyset` on
`(priority, report_date, id)` is the index `services/api/pagination.py` was written against.

**`report_flight_links` is many-to-many, scored.** A report can have several plausible
flight candidates; `db/repo.py` picks the highest-`confidence` one as "the" linked flight
for display, but every candidate the linkage query found stays on the table.
