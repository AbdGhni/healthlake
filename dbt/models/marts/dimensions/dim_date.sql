-- Grain: one calendar day (UTC) between the first and last clinical event of the release.
with bounds as (
    select min((d at time zone 'UTC')::date) as lo, max((d at time zone 'UTC')::date) as hi from (
        select start_at as d from {{ ref('int_encounter') }}
        union all select onset_at from {{ ref('stg_condition') }}
        union all select effective_at from {{ ref('stg_observation') }}
        union all select authored_at from {{ ref('stg_medication_request') }}
    ) x where d is not null
)
select
    to_char(day, 'YYYYMMDD')::int  as date_key,
    day::date                      as calendar_date,
    extract(year from day)::int    as year,
    extract(month from day)::int   as month,
    extract(isodow from day)::int  as iso_weekday
from bounds, generate_series(bounds.lo, bounds.hi, interval '1 day') as day
