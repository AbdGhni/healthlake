# HealthLake : rapport final

> HealthLake is a technical demonstration using synthetic data only.
> It is not a certified healthcare platform and is not intended or
> authorized to process real personal health data.

Date : 15 octobre 2026.

- Dépôt local : 13 commits, 278 fichiers suivis, environ 11 900 lignes de Python.
- Publié sur https://github.com/AbdGhni/healthlake, avec une CI entièrement verte.
- Tout ce qui est marqué « vérifié » a été exécuté. Tout ce qui ne l'a pas été est marqué « non vérifié », avec
  la cause et la commande à lancer.

## 1. Résumé
HealthLake ingère trois sources hospitalières fictives générées par Synthea 4.0.0 :
- `horizon-central` en FHIR ;
- `horizon-nord` en CSV ;
- `horizon-sud` en JSON.

Le pipeline :
1. vérifie chaque lot avec son manifeste ;
2. l'archive à l'identique dans un stockage adressé par SHA-256 ;
3. le convertit en FHIR R4 ;
4. le valide et résout les références dans le namespace de sa source ;
5. charge une couche Silver historisée dans PostgreSQL ;
6. construit un modèle Gold dbt dans un schéma candidat ;
7. ne le publie, par bascule atomique, qu'après une porte qualité.

Une API FastAPI en lecture seule et un tableau de bord Streamlit servent la release active. Airflow 3 orchestre
le tout. Tout fonctionne en local et a été mesuré jusqu'à 1,8 million de ressources FHIR.

## 2. Livrables
| Domaine | Contenu | Où |
|---|---|---|
| Ingestion et Bronze | manifestes, registre, RawStore SHA-256, vérification et re-hachage | `src/healthlake/ingestion` |
| FHIR | adaptateurs CSV/JSON vers FHIR R4, validation structurelle bloquante, audit par le validateur HL7 officiel sur échantillon, résolution des références | `adapters/`, `validation/`, `normalization/` |
| Silver | versions historisées, 4 statuts disjoints, rapprochement des comptes, porte de traitement, quarantaine | migrations 0001-0009, `pipelines/` |
| Gold | dbt : 5 dimensions, 6 faits, 6 agrégats, 100 tests, index de service ; snapshot déterministe, schéma candidat, porte de release, publication atomique, rétention | `dbt/`, `release/` |
| Orchestration | DAGs `healthlake_discovery` et `healthlake_ingestion`, contrat de codes de sortie, relances seulement pour les erreurs transitoires, `final_report` comme unique feuille | `airflow/dags` |
| API | 13 routes ; clés hachées avec portées ; curseurs signés liés à une release ; 401/403/404/410/422/503 ; `/metrics` | `api/`, `docs/api` |
| Tableau de bord | 6 pages, uniquement via l'API, définitions d'indicateurs | `dashboards/` |
| Exploitation | logs JSON expurgés, métriques Prometheus, 10 runbooks, sauvegarde et restauration vérifiées, `gc-work` | `docs/runbooks`, `scripts/` |
| Déploiement | 3 Dockerfiles, `docker-compose.yml` (10 services), bootstrap, scénarios de démo, CI GitHub Actions | racine, `infrastructure/`, `.github/` |
| Documentation | README en anglais, 7 diagrammes, dictionnaire de données généré, contrat de données, 5 ADR, journal des décisions, rapport de tests, rapport de performance, limites connues | `docs/`, `architecture/` |
| Portfolio | démo de 5 min, présentation de 15 min, textes CV et LinkedIn (EN/FR), questions d'entretien, backlog | `docs/portfolio` |

## 3. Vérifié (exécuté)
| Vérification | Commande | Résultat |
|---|---|---|
| Tests applicatifs, depuis un clone propre du dépôt | `pytest -q` | 81 réussis |
| Tests des DAGs, avec un `AIRFLOW_HOME` vide comme en CI | `pytest -q tests/airflow` | 12 réussis |
| Tests du tableau de bord | `pytest -q tests/dashboard` | 10 réussis |
| Tests dbt | à chaque build de release | 100/100 (profils test, démo et étendu) |
| Qualité du code | `ruff check`, `ruff format --check`, `mypy --strict src` | propre |
| 5 scénarios de démo, profil démo, base neuve | `scripts/demo.py --scenario all --runner local --profile demo` | tous réussis |
| Airflow 3.3.2 réel (scheduler, dag-processor, api-server) sur PostgreSQL | phase 7 | exécutions réussies, pas de doublon, pas de relance sur erreur de données |
| Sauvegarde et restauration, y compris le refus d'une sauvegarde corrompue | `scripts/backup.py`, `restore.py --runner local` | vérifié |
| Performance, profils démo et étendu | `scripts/perf_pipeline.py`, `perf_api.py` | voir section 5 |
| Rendu des 8 diagrammes Mermaid | mermaid-cli 11.4.2 | 8 sur 8 |
| Liens relatifs de la documentation | script de contrôle | 0 lien cassé |
| `docker compose config`, avec et sans le profil `tools` | depuis le clone propre | valide |
| Vulnérabilités des dépendances | `pip-audit` sur les 4 lockfiles | aucune connue |
| Secrets | `gitleaks` sur tout l'historique | aucune fuite |
| Avertissement obligatoire | README, `docs/api`, OpenAPI, tableau de bord | présent |

## 4. Vérifié en intégration continue (GitHub Actions)
Dépôt public : https://github.com/AbdGhni/healthlake. Chaque push lance 6 jobs sur Ubuntu. La
[dernière exécution](https://github.com/AbdGhni/healthlake/actions/runs/38810331362) est entièrement verte :
- lint, mypy (y compris les scripts), pip-audit et gitleaks sur tout l'historique ;
- tests applicatifs sur **PostgreSQL 17.11** ;
- tests des DAGs et du tableau de bord ;
- **e2e** : build des 3 images, scan Trivy, `docker compose up` avec tous les healthchecks, les **5 scénarios de
  démo via Airflow 3 en conteneurs**, puis **sauvegarde et restauration** avec le runner Docker (Bronze
  re-haché, comptes rapprochés, test de l'API sur la release restaurée).

Les premières exécutions de la CI ont trouvé 7 défauts, tous corrigés :
- fixtures de test sans mot de passe ;
- gitleaks-action en échec au premier push ;
- permissions des jars dans l'image ;
- secrets Airflow lus avec un retour à la ligne ;
- dossier de sauvegarde monté en bind mount ;
- réinitialisation des mots de passe absente dans la restauration Docker ;
- sauvegarde qui gelait les runs en cours.

## 4 bis. Non vérifié
| Élément | Cause | Commande pour vérifier |
|---|---|---|
| Docker Desktop sous Windows (l'hôte visé) | la CI tourne sous Linux | `python scripts/bootstrap.py` puis `make build up demo` depuis PowerShell |
| Images arm64 | la CI ne construit que pour amd64 | `docker compose build` sur une machine arm64 |
| Profil étendu via Airflow en conteneurs, et profil étendu à chaud | budget de temps et de disque | `docker compose run --rm synthea --profile extended --revision 1` |
| Java 17 | Temurin 21 retenu (justifié dans `docs/deployment.md`) | sans objet |

## 5. Performances mesurées
Conditions : VM partagée, 2 vCPU, 7 Go de RAM, sans Docker.

| | Démo (100 patients par source) | Étendu (1 000 par source) |
|---|---|---|
| Ressources | 160 111 | 1 791 707 |
| Génération | 205 s | 1 271 s |
| Pipeline complet, à froid | 239 s (244 s à chaud) | 1 841 s |
| Pic mémoire, plus gros processus | 1,87 Go | 2,68 Go |
| Base de données | 0,9 Go | 10,6 Go |
| API, 5 clients, p95 à chaud | 68 ms (agrégats), 76 ms (listes) | 68 ms, 76 ms |

Objectif « p95 des agrégats < 500 ms » : atteint. Il ne l'était pas avant les corrections de la section 6.
L'analyse détaillée est dans `docs/performance/README.md`.

## 6. Défauts trouvés par les tests et les mesures, puis corrigés
Phases 1 à 11 :
- un rollback qui perdait la quarantaine ;
- des identifiants NPI résolus entre sources, ce qui fusionnait des établissements ;
- des bornes de `dim_date` qui n'étaient pas en UTC ;
- des horodatages de l'API renvoyés en +02:00 ;
- un rapport final relancé à tort ;
- des sauvegardes qui contenaient des vérificateurs de mots de passe ;
- des scénarios de démo dérivés de lots bloqués.

Phase 12, chaque correction a été re-mesurée ou testée :
- **génération** tuée par manque de mémoire à 5,7 Go : elle lit maintenant les fichiers en flux, pic à 1,45 Go,
  lots identiques à l'octet près ;
- **API** à environ 1 s de p95 : index Gold, résumé précalculé et filtre sur la clé indexée la ramènent sous
  80 ms ;
- **snapshot** de 200 s ramené à 50 s (migration 0008) ;
- **statistiques périmées** : deux modèles dbt tournaient encore après 13 minutes ; la migration 0009 les
  rafraîchit avant dbt ;
- **tests des DAGs** qui auraient échoué en CI faute de base Airflow.

## 7. Écarts par rapport au prompt, et pourquoi
- **Java 21 au lieu de 17**, version épinglée par somme de contrôle : c'est la version testée avec Synthea et le
  validateur HL7.
- **Tests sur PostgreSQL 16** alors que Compose et la CI ciblent PostgreSQL 17 : c'est ce qui est disponible
  dans le sandbox.
- **Validateur HL7 sur échantillon**, la validation structurelle couvrant tout (ADR 0003) : le validateur sur
  1,8 M de ressources prendrait des heures.
- **argparse au lieu de typer** : une dépendance de moins, et le contrôle total de la sortie JSON et des codes
  de sortie.
- **Swagger UI chargé depuis un CDN** (comportement par défaut de FastAPI) : `/openapi.json` fonctionne hors
  ligne. C'est une limite documentée.
- **Formats CSV/JSON propres à HealthLake** : ils sont dérivés du FHIR de Synthea, ce ne sont pas les exports
  CSV de Synthea.

## 8. Sécurité et conformité
Données synthétiques uniquement : aucune donnée personnelle réelle n'a été introduite.

- Les secrets sont dans `.secrets/`, hors Git, et lus via `*_FILE`. `.env.example` ne contient aucun secret.
- Rôles PostgreSQL à moindre privilège ; l'ingestion n'obtient qu'une seule fonction `SECURITY DEFINER`, et
  elle est testée.
- Clés d'API stockées hachées et comparées en temps constant.
- Conteneurs non-root, ports exposés sur 127.0.0.1 uniquement.
- Images épinglées par digest, paquets par hash, actions CI par commit.

Le dépôt a été créé et poussé sur GitHub à ta demande. Rien n'a été déployé ni payé, et aucune configuration globale de
machine n'a été modifiée.

## 9. Limites connues
Voir `docs/known-limits.md`, en particulier :
- pas un produit médical ;
- un seul nœud ;
- pas de serveur de terminologie ;
- pas de rapprochement de patients entre sources ;
- la mémoire de la résolution croît avec la taille du lot.

## 10. Ce qui reste de ton côté
- Le dépôt est créé et poussé avec ton accord du 15 octobre.
- Il reste à lancer la stack sur ton PC avec Docker Desktop (`python scripts/bootstrap.py`, puis
  `make build up demo`). C'est la seule vérification de plateforme encore ouverte.

## 11. Suites possibles
Voir `docs/portfolio/extension-backlog.md` :
1. vérifier la stack sous Docker Desktop (Windows) ;
2. charger Silver dans des tables de staging non indexées ;
3. résolution des références par morceaux ;
4. validation en parallèle ;
5. modèles dbt incrémentaux.
