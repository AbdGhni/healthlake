-- Grain: one processing included in the release. Reconciliation counters + issues by severity.
with procs as (
    select rp.processing_id
    from {{ source('ctl', 'release_processing') }} rp
    where rp.release_id = '{{ var("release_id") }}'
),
issues as (
    select processing_id,
           count(*) filter (where severity = 'fatal')   as fatal_issues,
           count(*) filter (where severity = 'error')   as error_issues,
           count(*) filter (where severity = 'warning') as warning_issues
    from {{ source('quality', 'issue') }}
    where processing_id in (select processing_id from procs)
    group by processing_id
)
select
    p.processing_id, b.source_id, b.source_revision, p.status,
    (p.counters->>'received')::bigint      as received,
    (p.counters->>'accepted')::bigint      as accepted,
    (p.counters->>'deduplicated')::bigint  as deduplicated,
    (p.counters->>'rejected')::bigint      as rejected,
    (p.counters->>'out_of_scope')::bigint  as out_of_scope,
    (p.counters->>'reject_rate_new')::numeric as reject_rate_new,
    coalesce(i.fatal_issues, 0)            as fatal_issues,
    coalesce(i.error_issues, 0)            as error_issues,
    coalesce(i.warning_issues, 0)          as warning_issues,
    p.loaded_at
from procs
join {{ source('ctl', 'processing') }} p using (processing_id)
join {{ source('ctl', 'batch') }} b on b.batch_id = p.batch_id
left join issues i using (processing_id)
