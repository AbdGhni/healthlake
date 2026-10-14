-- Grain: one row per encounter version selected in the release snapshot.
select s.*
from {{ source('silver', 'encounter') }} s
{{ in_snapshot('s') }}
