-- Grain: one observation identity, with canonical numeric value when an approved conversion exists.
select
    o.*,
    uc.to_unit_code                                         as canonical_unit_code,
    case when uc.from_unit_code is not null and o.value_numeric is not null
         then o.value_numeric * uc.factor + uc.offset_value end as value_canonical
from {{ ref('stg_observation') }} o
left join {{ ref('unit_conversion') }} uc on uc.from_unit_code = o.value_unit_code
