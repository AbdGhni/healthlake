-- The approved conversion table reproduces reference values (tolerance 1e-9).
with cases(from_unit, value, expected) as (
  values ('[lb_av]', 100.0, 45.359237), ('[in_i]', 10.0, 25.4), ('[degF]', 212.0, 100.0), ('[degF]', 32.0, 0.0)
)
select c.* from cases c join {{ ref('unit_conversion') }} u on u.from_unit_code = c.from_unit
where abs(c.value * u.factor + u.offset_value - c.expected) > 1e-9
