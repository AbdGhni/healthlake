-- Grain: one observation identity. value[x] kept explicit; no imputation.
select
    o.entity_id                                  as observation_key,
    o.patient_entity_id                          as patient_key,
    o.encounter_entity_id                        as encounter_key,
    {{ code_key('o.code_system', 'o.code') }}    as code_key,
    o.source_id, o.status, o.category_code,
    o.effective_raw, o.effective_precision, o.effective_at,
    case when o.effective_at is not null then to_char(o.effective_at at time zone 'UTC', 'YYYYMMDD')::int end
                                                 as effective_date_key,
    o.value_type, o.value_numeric, o.value_unit, o.value_unit_code,
    o.canonical_unit_code, o.value_canonical,
    o.value_string, o.value_boolean,
    case when o.value_code is not null then {{ code_key('o.value_code_system', 'o.value_code') }} end as value_code_key,
    o.value_datetime, o.data_absent_reason, o.component_count, o.resource_version_id
from {{ ref('int_observation_value') }} o
