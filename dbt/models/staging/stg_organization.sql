-- Grain: one row per organization version selected in the release snapshot.
select s.*
from {{ source('silver', 'organization') }} s
{{ in_snapshot('s') }}
