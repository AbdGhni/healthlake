select encounter_key from {{ ref('fct_encounter') }} where end_at < start_at
union all
select condition_key from {{ ref('fct_condition') }} where abatement_at < onset_at
