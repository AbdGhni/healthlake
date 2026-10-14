-- Grain: one row per observation_component version selected in the release snapshot.
select s.*
from {{ source('silver', 'observation_component') }} s
{{ in_snapshot('s') }}
