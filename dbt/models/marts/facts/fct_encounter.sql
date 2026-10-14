-- Grain: one encounter identity.
select
    encounter_key, patient_key, organization_key, source_id, status, class_code, encounter_category,
    type_code_key, start_at, end_at,
    case when start_at is not null then to_char(start_at at time zone 'UTC', 'YYYYMMDD')::int end as start_date_key,
    duration_minutes, resource_version_id
from {{ ref('int_encounter') }}
