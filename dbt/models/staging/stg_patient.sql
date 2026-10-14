-- Grain: one row per patient version selected in the release snapshot.
select s.*
from {{ source('silver', 'patient') }} s
{{ in_snapshot('s') }}
