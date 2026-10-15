-- The precomputed summary must equal the facts it summarises (one row, same counts; breakdowns add up).
with s as (select * from {{ ref('agg_summary') }}),
b as (
    select
        sum(encounters) filter (where breakdown = 'category') as enc_by_category,
        sum(encounters) filter (where breakdown = 'source')   as enc_by_source,
        sum(patients)   filter (where breakdown = 'source')   as patients_by_source
    from {{ ref('agg_summary_breakdown') }}
)
select 'row_count' as problem from (select count(*) as n from s) c where c.n <> 1
union all
select 'patients' from s where s.patients <> (select count(*) from {{ ref('dim_patient') }})
union all
select 'encounters' from s where s.encounters <> (select count(*) from {{ ref('fct_encounter') }})
union all
select 'observations' from s where s.observations <> (select count(*) from {{ ref('fct_observation') }})
union all
select 'medication_requests' from s
where s.medication_requests <> (select count(*) from {{ ref('fct_medication_request') }})
union all
select 'category_breakdown' from s, b where coalesce(b.enc_by_category, 0) <> s.encounters
union all
select 'source_breakdown' from s, b
where coalesce(b.enc_by_source, 0) <> s.encounters or coalesce(b.patients_by_source, 0) <> s.patients
