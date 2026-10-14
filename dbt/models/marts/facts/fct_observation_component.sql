-- Grain: one component of one observation (observation_key, ordinal).
select
    o.entity_id                                   as observation_key,
    c.ordinal,
    {{ code_key('c.code_system', 'c.code') }}     as code_key,
    c.value_type, c.value_numeric, c.value_unit, c.value_unit_code, c.value_string, c.value_boolean,
    case when c.value_code is not null then {{ code_key('c.value_code_system', 'c.value_code') }} end as value_code_key,
    c.data_absent_reason, o.source_id, c.resource_version_id
from {{ ref('stg_observation_component') }} c
join {{ ref('stg_observation') }} o using (resource_version_id)
