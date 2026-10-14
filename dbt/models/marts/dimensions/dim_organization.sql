-- Grain: one organization identity.
select entity_id as organization_key, source_id, name, org_type_code, active, resource_version_id
from {{ ref('stg_organization') }}
