-- Indexes serve the API keyset order and its equality filters (src/healthlake/api/app.py).
{{ config(post_hook=[
        "create index on {{ this }} (activity_date, source_id, encounter_category)"
    ]) }}
-- Grain: one (activity_date, source_id, encounter_category). Encounters counted once, by start date (UTC).
select
    (start_at at time zone 'UTC')::date          as activity_date,
    start_date_key,
    source_id,
    encounter_category,
    count(*)                                     as encounters,
    count(distinct patient_key)                  as distinct_patients
from {{ ref('fct_encounter') }}
where start_at is not null
group by 1, 2, 3, 4
