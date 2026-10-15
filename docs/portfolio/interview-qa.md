# Interview questions and answers

Short answers you can give out loud, with a pointer to where the evidence is.

**1. Why synthetic data only?**
Real health data is special-category personal data under the GDPR, and France requires HDS-certified hosting for it.
A portfolio project cannot meet those obligations, so HealthLake refuses the use case explicitly. The disclaimer
appears in the README, the API docs and the dashboard. Synthea gives realistic FHIR data with fixed seeds.

**2. What happens if the same batch arrives twice?**
Nothing changes. The batch id is the SHA-256 of its manifest and the processing id is derived from it and the code
versions, so the second run finds the processing already `loaded`. The release id is a hash of its inputs, so no
new release appears either. The `idempotent-replay` scenario checks both (`scripts/demo.py`).

**3. What if the pipeline crashes in the middle of a load?**
The Silver load is a single transaction, so a crash leaves nothing behind. Steps decide what to do from the
database status first, then from done-markers in the work directory. A replay resumes at the first unfinished
step. Crash points 1-7 and a `kill -9` are tested (`tests/recovery`, `tests/integration/test_release.py`).

**4. Two workers pick up the same batch. What happens?**
Each attempt takes a PostgreSQL advisory lock on the processing id. The second one exits with code 4
(`processing_locked`), which Airflow treats as transient. A test runs both attempts concurrently.

**5. How do you avoid publishing a broken Gold model?**
dbt builds into a new candidate schema (`release_<hash>`). The release gate runs the dbt tests plus release
checks: terminology coverage, freshness, completeness, and a fault-injection guard. Publication is a single-row
update of `ctl.active_release` inside a transaction. Readers switch atomically, and a failed gate never touches
the active release.

**6. Why not validate everything with the official HL7 validator?**
Cost. The Java validator is accurate but slow, and a demo batch holds tens of thousands of resources. Every
resource goes through blocking structural validation. The HL7 validator audits a deterministic sample: one
patient bundle per FHIR batch and 300 resources per CSV/JSON batch. Its results are recorded as quality checks
(ADR 0003, `config/hl7-validation-policy.json`). That trade-off is stated as a limit.

**7. How do you handle bad rows without blocking everything?**
Every occurrence gets one outcome: rejected, deduplicated, out of scope or accepted. Rejected rows stay in
quarantine with an issue record. The processing gate blocks the whole batch only for structural problems: fatal
issues, identity conflicts, invalid updates, a reject rate of new resources above 1 %, or a reconciliation
mismatch. The `quarantine` scenario shows one bad value among 120 new observations being quarantined while the
batch is published.

**8. Why resolve identifiers only within a source?**
Matching patients across hospitals (an MPI) is a hard problem with real consequences. An early version resolved
NPI identifiers across sources and silently merged organisations. Scoping identifiers by source fixed that, and
cross-source matching is listed as a future extension with a review queue.

**9. How does API pagination stay consistent while new releases are published?**
Keyset pagination with an HMAC-signed cursor. The cursor pins the release id, the endpoint, a hash of the filters
and the last key. A purged release returns 410. A tampered cursor, or one reused on another endpoint or with other filters,
returns 422.

**10. How are secrets handled?**
They live in files under `.secrets/`, mounted at `/run/secrets` and read through `*_FILE` variables. API keys are
stored as SHA-256 hashes and compared in constant time. Logs pass through a redaction filter. gitleaks runs in CI
and on the full history.

**11. What did testing find?**
Real bugs, among others:
- a rollback that lost the quarantine status;
- cross-source identifier merging;
- dbt date bounds that were not UTC;
- API timestamps returned in the server's time zone;
- backups that contained password verifiers;
- a report step whose exit code caused useless retries.

Each one has a regression test. See docs/implementation-status.md.

**12. Where is the time spent, and how would you scale it?**
It depends on the size. On 100 patients per source, validation and resolution dominate. On 1 000 per source
(1.8 M resources, 31 min on a 2-vCPU VM), the Silver load becomes the largest step: 626 s, growing faster than the
data because of index maintenance (docs/performance/README.md).

The extended run also exposed three defects, all fixed and measured again:
- generation that held everything in memory (OOM at 5.7 GB, now 1.45 GB);
- an API with no Gold indexes and live counts (p95 about 1 s, now under 80 ms);
- a snapshot slowed by row-by-row foreign-key checks (200 s, now 50 s).

Next steps:
- load into unindexed staging and then index, or partition Silver by source;
- chunked reference resolution to bound memory;
- parallel validation workers;
- incremental dbt models for observations.

**13. What would you not claim about this project?**
That it is production-ready or compliant. It has not run on a Docker host yet, terminology is not checked
against a server, and it is single-node. docs/known-limits.md lists it all.
