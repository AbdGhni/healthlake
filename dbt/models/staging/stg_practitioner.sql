-- Grain: one row per practitioner version selected in the release snapshot.
select s.*
from {{ source('silver', 'practitioner') }} s
{{ in_snapshot('s') }}
