-- Grain: one row per release. Headline counts served by /v1/summary, computed once at build time
-- (a release is immutable, so counting million-row facts on every API call would be wasted work).
select
    (select count(*) from {{ ref('dim_patient') }})                 as patients,
    (select count(*) from {{ ref('fct_encounter') }})               as encounters,
    (select count(*) from {{ ref('fct_condition') }})               as conditions,
    (select count(*) from {{ ref('agg_diagnosis') }})               as distinct_diagnosis_codes,
    (select count(*) from {{ ref('fct_observation') }})             as observations,
    (select count(*) from {{ ref('fct_observation_component') }})   as observation_components,
    (select count(*) from {{ ref('fct_medication_request') }})      as medication_requests,
    (select min(start_at) from {{ ref('fct_encounter') }})          as first_encounter_at,
    (select max(start_at) from {{ ref('fct_encounter') }})          as last_encounter_at
