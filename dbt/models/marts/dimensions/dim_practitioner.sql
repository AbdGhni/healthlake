-- Grain: one practitioner identity. No names.
select entity_id as practitioner_key, source_id, gender, active, resource_version_id
from {{ ref('stg_practitioner') }}
