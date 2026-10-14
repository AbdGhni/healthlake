-- HealthLake 0002: control plane and Bronze registry.

CREATE TABLE ctl.source (
  source_id      text PRIMARY KEY CHECK (source_id ~ '^[a-z][a-z0-9-]{1,62}$'),
  display_name   text NOT NULL,
  source_format  text NOT NULL CHECK (source_format IN ('fhir-r4-bundle','horizon-csv-v1','horizon-json-v1')),
  namespace_uuid uuid NOT NULL UNIQUE,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ctl.batch (
  batch_id         text PRIMARY KEY CHECK (batch_id ~ '^[0-9a-f]{64}$'),
  source_id        text NOT NULL REFERENCES ctl.source,
  source_revision  bigint NOT NULL CHECK (source_revision > 0),
  manifest         jsonb NOT NULL,
  manifest_sha256  text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  landing_path     text NOT NULL,
  status           text NOT NULL CHECK (status IN ('registered','verified','archived','invalid')),
  status_reason    text,
  registered_at    timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, source_revision)
);

CREATE TABLE ctl.processing (
  processing_id       text PRIMARY KEY CHECK (processing_id ~ '^[0-9a-f]{64}$'),
  batch_id            text NOT NULL REFERENCES ctl.batch,
  code_version        text NOT NULL,
  mapping_version     text NOT NULL,
  validation_version  text NOT NULL,
  status              text NOT NULL CHECK (status IN
                        ('pending','archived','adapted','validated','normalized','loaded','blocked','failed')),
  status_reason       text,
  counters            jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  loaded_at           timestamptz,
  UNIQUE (batch_id, code_version, mapping_version, validation_version)
);

CREATE TABLE ctl.attempt (
  attempt_id     uuid PRIMARY KEY,
  processing_id  text NOT NULL REFERENCES ctl.processing,
  orchestrator_run_id text,
  status         text NOT NULL CHECK (status IN ('running','succeeded','failed','blocked')),
  current_step   text,
  error_code     text,
  error_message  text,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz
);
CREATE INDEX attempt_processing_idx ON ctl.attempt (processing_id, started_at);

CREATE TABLE ctl.release (
  release_id     text PRIMARY KEY CHECK (release_id ~ '^[0-9a-f]{64}$'),
  schema_name    text NOT NULL UNIQUE CHECK (schema_name ~ '^release_[0-9a-f]{16}$'),
  status         text NOT NULL CHECK (status IN ('building','built','gate_passed','gate_failed','published','failed','purged')),
  status_reason  text,
  gate_result    jsonb,
  code_version   text NOT NULL,
  params         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now(),
  built_at       timestamptz,
  published_at   timestamptz,
  purged_at      timestamptz
);

CREATE TABLE ctl.release_processing (
  release_id     text NOT NULL REFERENCES ctl.release,
  processing_id  text NOT NULL REFERENCES ctl.processing,
  PRIMARY KEY (release_id, processing_id)
);

-- Exactly one row; release_id NULL means nothing published yet.
CREATE TABLE ctl.active_release (
  singleton     boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  release_id    text REFERENCES ctl.release,
  activated_at  timestamptz
);
INSERT INTO ctl.active_release (singleton) VALUES (true);

CREATE TABLE ctl.event (
  event_id       bigserial PRIMARY KEY,
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  event          text NOT NULL,
  level          text NOT NULL DEFAULT 'info',
  batch_id       text,
  processing_id  text,
  attempt_id     uuid,
  release_id     text,
  payload        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX event_processing_idx ON ctl.event (processing_id, occurred_at);

CREATE TABLE bronze.file (
  sha256         text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes     bigint NOT NULL CHECK (size_bytes >= 0),
  mime_type      text NOT NULL,
  storage_key    text NOT NULL UNIQUE,
  archived_at    timestamptz NOT NULL DEFAULT now(),
  last_verified_at timestamptz
);

CREATE TABLE bronze.batch_file (
  batch_id       text NOT NULL REFERENCES ctl.batch,
  relative_path  text NOT NULL,
  sha256         text NOT NULL REFERENCES bronze.file,
  PRIMARY KEY (batch_id, relative_path)
);

-- One row per resource occurrence found in a processing (after adaptation to FHIR).
-- outcome categories are disjoint: received = accepted + deduplicated + rejected + out_of_scope.
CREATE TABLE bronze.resource_occurrence (
  processing_id       text NOT NULL REFERENCES ctl.processing,
  occurrence_no       integer NOT NULL,
  file_sha256         text NOT NULL REFERENCES bronze.file,
  locator             text NOT NULL,              -- JSON pointer or csv:<file>#line=<n>
  resource_type       text NOT NULL,
  source_resource_id  text,
  resource_sha256     text NOT NULL,
  entity_id           uuid,
  resource_version_id text,
  outcome             text NOT NULL CHECK (outcome IN ('accepted','deduplicated','rejected','out_of_scope')),
  PRIMARY KEY (processing_id, occurrence_no)
);
CREATE INDEX occurrence_entity_idx ON bronze.resource_occurrence (entity_id);
