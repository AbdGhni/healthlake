{# Rows of a Silver projection that belong to the release snapshot (one version per identity). #}
{% macro in_snapshot(alias) -%}
  join {{ source('silver', 'snapshot_member') }} sm
    on sm.resource_version_id = {{ alias }}.resource_version_id
   and sm.snapshot_id = '{{ var("snapshot_id") }}'
{%- endmacro %}

{% macro code_key(system, code) -%}
  md5(coalesce({{ system }}, '') || '|' || coalesce({{ code }}, ''))
{%- endmacro %}
