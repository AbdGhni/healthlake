{# Every relation of a release lives in the release schema chosen by the pipeline (no prefixes). #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ target.schema }}
{%- endmacro %}
