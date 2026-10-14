-- Grain: one row per observation version selected in the release snapshot.
select s.*
from {{ source('silver', 'observation') }} s
{{ in_snapshot('s') }}
