-- Grain: one (system, code) pair used by a fact of the release.
with used as (
    select type_system as system, type_code as code, null::text as display, 'encounter.type' as usage
      from {{ ref('stg_encounter') }} where type_code is not null
    union all
    select code_system, code, code_display, 'condition.code' from {{ ref('stg_condition') }} where code is not null
    union all
    select code_system, code, code_display, 'observation.code' from {{ ref('stg_observation') }} where code is not null
    union all
    select value_code_system, value_code, value_code_display, 'observation.value'
      from {{ ref('stg_observation') }} where value_code is not null
    union all
    select c.code_system, c.code, c.code_display, 'component.code'
      from {{ ref('stg_observation_component') }} c
      join {{ ref('stg_observation') }} o using (resource_version_id) where c.code is not null
    union all
    select c.value_code_system, c.value_code, null, 'component.value'
      from {{ ref('stg_observation_component') }} c
      join {{ ref('stg_observation') }} o using (resource_version_id) where c.value_code is not null
    union all
    select medication_system, medication_code, medication_display, 'medication.code'
      from {{ ref('stg_medication_request') }} where medication_code is not null
)
select
    {{ code_key('system', 'code') }}                   as code_key,
    system,
    code,
    min(display)                                      as display,
    array_agg(distinct usage order by usage)          as usages,
    case
        when system = 'http://snomed.info/sct' then 'SNOMED CT'
        when system = 'http://loinc.org' then 'LOINC'
        when system = 'http://www.nlm.nih.gov/research/umls/rxnorm' then 'RxNorm'
        when system is null then 'no system'
        else 'other'
    end                                               as system_label
from used
group by system, code
