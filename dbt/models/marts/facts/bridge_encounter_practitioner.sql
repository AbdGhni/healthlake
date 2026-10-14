-- Grain: one practitioner participation in one encounter (encounter_key, ordinal).
select e.entity_id as encounter_key, p.ordinal, p.practitioner_entity_id as practitioner_key, p.type_code
from {{ ref('stg_encounter_participant') }} p
join {{ ref('stg_encounter') }} e using (resource_version_id)
