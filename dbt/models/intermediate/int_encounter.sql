-- Grain: one encounter identity, with reporting category and duration.
select
    e.entity_id                                   as encounter_key,
    e.patient_entity_id                           as patient_key,
    e.service_provider_entity_id                  as organization_key,
    e.source_id,
    e.status,
    e.class_code,
    coalesce(c.encounter_category, 'other')       as encounter_category,
    case when e.type_code is not null then {{ code_key('e.type_system', 'e.type_code') }} end as type_code_key,
    e.period_start                                as start_at,
    e.period_end                                  as end_at,
    -- NULL when the encounter has no end (still open) or no instant: never imputed.
    case when e.period_start is not null and e.period_end is not null
         then round(extract(epoch from e.period_end - e.period_start) / 60.0, 2) end as duration_minutes,
    e.resource_version_id
from {{ ref('stg_encounter') }} e
left join {{ ref('encounter_class_category') }} c on c.class_code = e.class_code
