-- Grain: one row per condition version selected in the release snapshot.
select s.*
from {{ source('silver', 'condition') }} s
{{ in_snapshot('s') }}
