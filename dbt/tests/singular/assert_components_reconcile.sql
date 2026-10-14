select observation_key from {{ ref('fct_observation') }} o
left join (select observation_key, count(*) n from {{ ref('fct_observation_component') }} group by 1) c
  using (observation_key)
where o.component_count <> coalesce(c.n, 0)
