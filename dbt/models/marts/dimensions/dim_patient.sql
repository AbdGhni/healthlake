-- Indexes serve the API keyset order and its equality filters (src/healthlake/api/app.py).
{{ config(post_hook=[
        "create index on {{ this }} (patient_key)"
    ]) }}
-- Grain: one synthetic patient identity (per source namespace; no cross-source merge).
select
    p.entity_id                                       as patient_key,
    p.source_id,
    p.gender,
    case when p.birth_date_precision is not null then left(p.birth_date_raw, 4)::int end as birth_year,
    p.birth_date_precision,
    coalesce(p.deceased, false)                       as deceased,
    p.managing_organization_entity_id                 as organization_key,
    p.resource_version_id
from {{ ref('stg_patient') }} p
