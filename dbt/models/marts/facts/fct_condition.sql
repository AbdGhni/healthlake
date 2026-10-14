-- Grain: one condition identity.
select
    c.entity_id                                  as condition_key,
    c.patient_entity_id                          as patient_key,
    c.encounter_entity_id                        as encounter_key,
    {{ code_key('c.code_system', 'c.code') }}    as code_key,
    c.source_id, c.clinical_status, c.verification_status, c.category_code,
    c.onset_raw, c.onset_precision, c.onset_at,
    case when c.onset_at is not null then to_char(c.onset_at at time zone 'UTC', 'YYYYMMDD')::int end as onset_date_key,
    c.abatement_at, c.recorded_at, c.resource_version_id
from {{ ref('stg_condition') }} c
