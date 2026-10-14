-- Aggregates must add up to their facts (one row per failing check).
select 'activity' as check_name from (
  select (select coalesce(sum(encounters), 0) from {{ ref('agg_activity_daily') }}) as a,
         (select count(*) from {{ ref('fct_encounter') }} where start_at is not null) as f) x where a <> f
union all
select 'diagnosis' from (
  select (select coalesce(sum(conditions), 0) from {{ ref('agg_diagnosis') }}) as a,
         (select count(*) from {{ ref('fct_condition') }}) as f) x where a <> f
union all
select 'observation_volume' from (
  select (select coalesce(sum(observations), 0) from {{ ref('agg_observation_volume') }}) as a,
         (select count(*) from {{ ref('fct_observation') }}) as f) x where a <> f
