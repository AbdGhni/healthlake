-- Grain: one (breakdown, item). breakdown 'category': encounters per encounter_category (all encounters,
-- with or without a start); breakdown 'source': patients and encounters per source.
select 'category'::text as breakdown, encounter_category as item, null::bigint as patients, count(*) as encounters
from {{ ref('fct_encounter') }}
group by encounter_category
union all
select 'source', p.source_id, p.patients, coalesce(e.encounters, 0)
from (select source_id, count(*) as patients from {{ ref('dim_patient') }} group by 1) p
left join (select source_id, count(*) as encounters from {{ ref('fct_encounter') }} group by 1) e using (source_id)
