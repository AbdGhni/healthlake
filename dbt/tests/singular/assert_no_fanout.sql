-- Each fact has exactly one row per staging identity (joins did not multiply rows).
select 'fct_encounter' as model from (select (select count(*) from {{ ref('fct_encounter') }}) a,
  (select count(*) from {{ ref('stg_encounter') }}) b) x where a <> b
union all
select 'fct_condition' from (select (select count(*) from {{ ref('fct_condition') }}) a,
  (select count(*) from {{ ref('stg_condition') }}) b) x where a <> b
union all
select 'fct_observation' from (select (select count(*) from {{ ref('fct_observation') }}) a,
  (select count(*) from {{ ref('stg_observation') }}) b) x where a <> b
union all
select 'fct_medication_request' from (select (select count(*) from {{ ref('fct_medication_request') }}) a,
  (select count(*) from {{ ref('stg_medication_request') }}) b) x where a <> b
