-- Grain: one diagnosis code (code_key). Counts come from fct_condition only (no fact-to-fact join).
select
    c.code_key, d.system, d.system_label, d.code, d.display,
    count(*)                                     as conditions,
    count(distinct c.patient_key)                as distinct_patients,
    min(c.onset_at)                              as first_onset_at,
    max(c.onset_at)                              as last_onset_at
from {{ ref('fct_condition') }} c
join {{ ref('dim_code') }} d using (code_key)
group by 1, 2, 3, 4, 5
