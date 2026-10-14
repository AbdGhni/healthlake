-- HealthLake 0003: Silver. Versions are append-only; projections are keyed by resource_version_id.

CREATE TABLE silver.resource_version (
  resource_version_id text PRIMARY KEY CHECK (resource_version_id ~ '^[0-9a-f]{64}$'),
  entity_id           uuid NOT NULL,
  source_id           text NOT NULL REFERENCES ctl.source,
  resource_type       text NOT NULL,
  source_resource_id  text NOT NULL,
  first_source_revision bigint NOT NULL,  -- revision where this exact content first appeared
  resource_sha256     text NOT NULL,
  mapping_version     text NOT NULL,
  meta_version_id     text,                -- kept as text, never compared numerically
  in_analytic_scope   boolean NOT NULL,
  resource            jsonb NOT NULL,
  first_processing_id text NOT NULL REFERENCES ctl.processing,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX resource_version_entity_idx ON silver.resource_version (entity_id);

CREATE TABLE silver.resource_lineage (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  processing_id       text NOT NULL,
  occurrence_no       integer NOT NULL,
  PRIMARY KEY (resource_version_id, processing_id, occurrence_no),
  FOREIGN KEY (processing_id, occurrence_no) REFERENCES bronze.resource_occurrence
);

CREATE TABLE silver.processing_resource (
  processing_id       text NOT NULL REFERENCES ctl.processing,
  entity_id           uuid NOT NULL,
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  source_revision     bigint NOT NULL,     -- business order used by snapshots
  PRIMARY KEY (processing_id, entity_id)
);
CREATE INDEX processing_resource_entity_idx ON silver.processing_resource (entity_id, source_revision DESC);

CREATE TABLE silver.reference (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  path                text NOT NULL,       -- e.g. subject, encounter, participant[0].individual
  raw_reference       text NOT NULL,
  resolution_method   text NOT NULL CHECK (resolution_method IN
                        ('fullUrl','urn_uuid','relative','absolute','contained','identifier')),
  target_type         text NOT NULL,
  target_entity_id    uuid,                -- NULL only for contained targets
  PRIMARY KEY (resource_version_id, path)
);
CREATE INDEX reference_target_idx ON silver.reference (target_entity_id);

CREATE TABLE silver.identifier (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  ordinal             integer NOT NULL,
  entity_id           uuid NOT NULL,
  source_id           text NOT NULL,       -- identifiers resolve only inside their source namespace
  resource_type       text NOT NULL,
  system              text NOT NULL,
  value               text NOT NULL,
  PRIMARY KEY (resource_version_id, ordinal)
);
CREATE INDEX identifier_lookup_idx ON silver.identifier (source_id, resource_type, system, value);

CREATE TABLE silver.coding (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  path                text NOT NULL,
  ordinal             integer NOT NULL,
  system              text,
  version             text,
  code                text,
  display             text,
  user_selected       boolean,
  PRIMARY KEY (resource_version_id, path, ordinal)
);

-- Projections. Dates keep original text plus precision; instants are UTC.
CREATE TABLE silver.patient (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  gender text, birth_date_raw text, birth_date_precision text, birth_date date,
  deceased boolean, deceased_at timestamptz,
  managing_organization_entity_id uuid
);
CREATE TABLE silver.organization (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  name text, org_type_code text, active boolean
);
CREATE TABLE silver.practitioner (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  gender text, active boolean
);
CREATE TABLE silver.encounter (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  patient_entity_id uuid NOT NULL,
  service_provider_entity_id uuid,
  status text NOT NULL, class_code text, type_system text, type_code text,
  period_start_raw text, period_start timestamptz, period_end_raw text, period_end timestamptz
);
CREATE TABLE silver.encounter_participant (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  ordinal integer NOT NULL,
  practitioner_entity_id uuid NOT NULL,
  type_code text,
  PRIMARY KEY (resource_version_id, ordinal)
);
CREATE TABLE silver.condition (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  patient_entity_id uuid NOT NULL, encounter_entity_id uuid,
  clinical_status text, verification_status text, category_code text,
  code_system text, code text, code_display text,
  onset_raw text, onset_precision text, onset_at timestamptz,
  abatement_raw text, abatement_at timestamptz,
  recorded_raw text, recorded_at timestamptz
);
CREATE TABLE silver.observation (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  patient_entity_id uuid NOT NULL, encounter_entity_id uuid,
  status text NOT NULL, category_code text,
  code_system text, code text, code_display text,
  effective_raw text, effective_precision text, effective_at timestamptz,
  value_type text NOT NULL CHECK (value_type IN
    ('Quantity','CodeableConcept','string','boolean','integer','dateTime','time','Period','none')),
  value_numeric numeric, value_unit text, value_unit_system text, value_unit_code text,
  value_string text, value_boolean boolean, value_code_system text, value_code text, value_code_display text,
  value_datetime_raw text, value_datetime timestamptz,
  data_absent_reason text,
  component_count integer NOT NULL DEFAULT 0
);
CREATE TABLE silver.observation_component (
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  ordinal integer NOT NULL,
  code_system text, code text, code_display text,
  value_type text NOT NULL,
  value_numeric numeric, value_unit text, value_unit_code text,
  value_string text, value_boolean boolean, value_code_system text, value_code text,
  data_absent_reason text,
  PRIMARY KEY (resource_version_id, ordinal)
);
CREATE TABLE silver.medication_request (
  resource_version_id text PRIMARY KEY REFERENCES silver.resource_version,
  entity_id uuid NOT NULL, source_id text NOT NULL,
  patient_entity_id uuid NOT NULL, encounter_entity_id uuid,
  requester_entity_id uuid,
  status text NOT NULL, intent text NOT NULL,
  medication_system text, medication_code text, medication_display text,
  authored_raw text, authored_at timestamptz
);

-- Deterministic snapshot: one member per identity, chosen by highest source_revision.
CREATE TABLE silver.snapshot_member (
  snapshot_id         text NOT NULL,
  entity_id           uuid NOT NULL,
  resource_version_id text NOT NULL REFERENCES silver.resource_version,
  resource_type       text NOT NULL,
  PRIMARY KEY (snapshot_id, entity_id)
);
CREATE TABLE silver.snapshot_reference (
  snapshot_id         text NOT NULL,
  from_entity_id      uuid NOT NULL,
  path                text NOT NULL,
  to_entity_id        uuid NOT NULL,
  PRIMARY KEY (snapshot_id, from_entity_id, path)
);
