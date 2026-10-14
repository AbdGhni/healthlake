-- Grain: one row per encounter_participant version selected in the release snapshot.
select s.*
from {{ source('silver', 'encounter_participant') }} s
{{ in_snapshot('s') }}
