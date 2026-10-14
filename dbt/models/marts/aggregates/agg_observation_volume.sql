-- Grain: one (code_key, value_type, value_unit_code). Statistics never mix codes or units.
select
    o.code_key, d.system, d.code, d.display, o.value_type, o.value_unit_code,
    count(*)                                     as observations,
    count(o.value_numeric)                       as numeric_values,
    count(o.data_absent_reason)                  as absent_values,
    count(distinct o.patient_key)                as distinct_patients,
    min(o.value_numeric)                         as min_value,
    avg(o.value_numeric)                         as mean_value,
    max(o.value_numeric)                         as max_value,
    min(o.effective_at)                          as first_effective_at,
    max(o.effective_at)                          as last_effective_at
from {{ ref('fct_observation') }} o
join {{ ref('dim_code') }} d using (code_key)
group by 1, 2, 3, 4, 5, 6
