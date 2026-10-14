-- Grain: one medication request identity.
select
    m.entity_id                                   as medication_request_key,
    m.patient_entity_id                           as patient_key,
    m.encounter_entity_id                         as encounter_key,
    m.requester_entity_id                         as practitioner_key,
    case when m.medication_code is not null then {{ code_key('m.medication_system', 'm.medication_code') }} end
                                                  as medication_code_key,
    m.source_id, m.status, m.intent, m.authored_at,
    case when m.authored_at is not null then to_char(m.authored_at at time zone 'UTC', 'YYYYMMDD')::int end
                                                  as authored_date_key,
    m.resource_version_id
from {{ ref('stg_medication_request') }} m
