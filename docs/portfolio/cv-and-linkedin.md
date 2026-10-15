# CV and LinkedIn texts

Adapt the numbers only from `docs/performance/README.md` and `docs/test-report.md`. Do not round them up.

## CV entry (English)
**HealthLake: synthetic healthcare data platform** (personal project, 2026). Python, PostgreSQL, dbt, Airflow 3,
FastAPI, Streamlit, Docker, FHIR R4.
- Built a batch pipeline that ingests three synthetic hospital sources (FHIR bundles, CSV, JSON). It archives
  every file by SHA-256, converts the data to FHIR R4, validates it, and loads a historised PostgreSQL model with
  full lineage.
- Made every step idempotent and crash-safe: deterministic identifiers, advisory locks, an exit-code contract
  driving Airflow retries. Crash scenarios, a hard kill and concurrent runs are tested.
- Published a dbt Gold model (100 data tests) through a quality gate and an atomic release switch. Served it with
  a read-only API (hashed keys, signed keyset cursors) and a dashboard.
- Measured performance per step and API latency under concurrent clients, and documented limits and runbooks.

## Entrée CV (français)
**HealthLake : plateforme de données de santé synthétiques** (projet personnel, 2026). Python, PostgreSQL,
dbt, Airflow 3, FastAPI, Streamlit, Docker, FHIR R4.
- Pipeline batch ingérant trois sources hospitalières fictives (FHIR, CSV, JSON). Chaque fichier est archivé
  par SHA-256 ; les données sont converties en FHIR R4, validées, puis chargées dans un modèle PostgreSQL
  historisé avec traçabilité complète.
- Étapes idempotentes et résistantes aux pannes : identifiants déterministes, verrous consultatifs, contrat de
  codes de sortie pilotant les relances Airflow. Crashs, arrêt brutal et exécutions concurrentes testés.
- Modèle Gold dbt (100 tests de données) publié via une porte qualité et une bascule atomique de release.
  Exposé par une API en lecture seule (clés hachées, curseurs signés) et un tableau de bord.
- Performances mesurées par étape et latence de l'API sous charge concurrente ; limites et runbooks documentés.

## LinkedIn project description (English)
HealthLake is a local data platform I built on **synthetic** healthcare data (Synthea). It is a technical
demonstration, not a medical product. Three fictional hospitals deliver FHIR, CSV and JSON batches. The pipeline
checks each delivery against its manifest, archives it unchanged, converts it to FHIR R4, validates it, and loads
a historised PostgreSQL layer. A dbt model is then built in a candidate schema and published atomically only if
its tests and quality checks pass. Airflow 3 orchestrates the steps, and a FastAPI service and a Streamlit
dashboard serve the active release.

What I focused on: idempotence and crash recovery (tested crash points, a hard kill and concurrent runs), honest
data-quality accounting (every record has exactly one outcome), security basics (file secrets, hashed API keys,
least-privilege database roles), and measured performance. Code, tests, runbooks and the list of known limits are
in the repository.

## Description LinkedIn (français)
HealthLake est une plateforme de données locale construite sur des données de santé **synthétiques** (Synthea).
C'est une démonstration technique, pas un produit médical. Trois hôpitaux fictifs livrent des lots FHIR, CSV et
JSON. Le pipeline vérifie chaque livraison avec son manifeste, l'archive à l'identique, la convertit en FHIR R4,
la valide et charge une couche PostgreSQL historisée. Un modèle dbt est ensuite construit dans un schéma candidat
et publié de façon atomique seulement si ses tests et ses contrôles qualité passent. Airflow 3 orchestre les
étapes ; une API FastAPI et un tableau de bord Streamlit exposent la release active.

Mes priorités : idempotence et reprise après panne (points de crash, arrêt brutal et exécutions concurrentes
testés), comptabilité qualité rigoureuse (chaque enregistrement a exactement un statut), sécurité de base
(secrets en fichiers, clés d'API hachées, rôles à privilèges minimaux) et performances mesurées. Code, tests,
runbooks et limites connues sont dans le dépôt.
