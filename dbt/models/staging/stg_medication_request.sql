-- Grain: one row per medication_request version selected in the release snapshot.
select s.*
from {{ source('silver', 'medication_request') }} s
{{ in_snapshot('s') }}
