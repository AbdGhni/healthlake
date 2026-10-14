-- HealthLake 0004: quality issues (quarantine) and check results.
CREATE TABLE quality.issue (
  issue_id            bigserial PRIMARY KEY,
  processing_id       text NOT NULL REFERENCES ctl.processing,
  attempt_id          uuid REFERENCES ctl.attempt,
  file_sha256         text,
  locator             text,
  resource_type       text,
  source_resource_id  text,
  check_id            text NOT NULL,
  severity            text NOT NULL CHECK (severity IN ('fatal','error','warning','info')),
  cause_code          text NOT NULL,
  message             text NOT NULL,
  caused_by_issue_id  bigint REFERENCES quality.issue,
  resolution_status   text NOT NULL DEFAULT 'open' CHECK (resolution_status IN ('open','superseded','accepted_risk','resolved')),
  resolution_note     text,
  resolved_by_processing_id text,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX issue_processing_idx ON quality.issue (processing_id, check_id);

CREATE TABLE quality.check_result (
  scope        text NOT NULL CHECK (scope IN ('processing','release')),
  scope_id     text NOT NULL,
  check_id     text NOT NULL,
  status       text NOT NULL CHECK (status IN ('pass','fail','warn','skipped')),
  observed     numeric,
  threshold    numeric,
  details      jsonb NOT NULL DEFAULT '{}'::jsonb,
  evaluated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, scope_id, check_id)
);
