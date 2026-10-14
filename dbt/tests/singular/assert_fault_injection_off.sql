-- Demonstration-only fault injection. `healthlake build-release` sets inject_gate_failure=true only when
-- HEALTHLAKE_INJECT_GATE_FAILURE=1 (used by the blocked-publication scenario and tests). It changes the
-- release id, so it can never alter a normal release.
select 'fault injection enabled' as reason
where {{ 'true' if var('inject_gate_failure', false) else 'false' }}
