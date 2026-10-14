-- Distribution of encounters per patient (analysis, not materialized).
select n_encounters, count(*) as patients
from (select patient_key, count(*) as n_encounters from {{ ref('fct_encounter') }} group by 1) x
group by 1 order by 1
