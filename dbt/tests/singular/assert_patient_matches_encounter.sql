-- Condition, Observation and MedicationRequest must belong to the patient of their encounter.
select 'condition' as fact, c.condition_key::text as key from {{ ref('fct_condition') }} c
join {{ ref('fct_encounter') }} e using (encounter_key) where c.patient_key <> e.patient_key
union all
select 'observation', o.observation_key::text from {{ ref('fct_observation') }} o
join {{ ref('fct_encounter') }} e using (encounter_key) where o.patient_key <> e.patient_key
union all
select 'medication_request', m.medication_request_key::text from {{ ref('fct_medication_request') }} m
join {{ ref('fct_encounter') }} e using (encounter_key) where m.patient_key <> e.patient_key
