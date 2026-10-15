# syntax=docker/dockerfile:1.7
# HealthLake platform image: Airflow 3 runtime + isolated HealthLake and dbt virtualenvs + Java 21 + HL7 validator
# + Synthea. Used by airflow-*, db-init, cli and synthea services.
ARG AIRFLOW_IMAGE=apache/airflow:3.3.2-python3.12@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1
FROM ${AIRFLOW_IMAGE}

USER root
ARG TARGETARCH
# Eclipse Temurin JRE 21.0.12.1+1 (LTS), pinned by SHA-256 per architecture.
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) arch=x64; sum=2413149700df0f7d440500a84a8f764c535f21e5a5e87d38328b64eec2c5b500 ;; \
      arm64) arch=aarch64; sum=14be1f35ebdbd1f6e8d57eb911a3ffb74d6d9aa255abc5daf2b1302002cf2cf2 ;; \
      *) echo "unsupported architecture ${TARGETARCH}"; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/jre.tgz "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_${arch}_linux_hotspot_21.0.12.1_1.tar.gz"; \
    echo "${sum}  /tmp/jre.tgz" | sha256sum -c -; \
    mkdir -p /opt/java; tar -xzf /tmp/jre.tgz -C /opt/java --strip-components=1; rm /tmp/jre.tgz; \
    /opt/java/bin/java -version
ENV JAVA_HOME=/opt/java
ENV PATH=/opt/java/bin:${PATH}

ADD --chmod=0444 --checksum=sha256:1178b6a3a3fe98d9cd9545cadee505274967332466001d857e4d8bed7138a5bc \
    https://github.com/hapifhir/org.hl7.fhir.core/releases/download/7.0.1/validator_cli.jar /opt/healthlake/validator_cli.jar
ADD --chmod=0444 --checksum=sha256:ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1 \
    https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar /opt/healthlake/synthea.jar

COPY requirements/app.lock requirements/dbt.lock /tmp/req/
RUN set -eux; export PIP_USER=false PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1; \
    python -m venv /opt/healthlake-venv; /opt/healthlake-venv/bin/pip install --require-hashes -r /tmp/req/app.lock; \
    python -m venv /opt/dbt-venv; /opt/dbt-venv/bin/pip install --require-hashes -r /tmp/req/dbt.lock; \
    /opt/healthlake-venv/bin/pip check; /opt/dbt-venv/bin/pip check; rm -rf /tmp/req

COPY --chown=root:root src /opt/healthlake/src
COPY --chown=root:root config /opt/healthlake/config
COPY --chown=root:root infrastructure/postgres/migrations /opt/healthlake/migrations
COPY --chown=root:root dbt /opt/healthlake/dbt
COPY --chown=root:root airflow/dags /opt/airflow/dags
COPY --chmod=0755 infrastructure/docker/healthlake-wrapper.sh /usr/local/bin/healthlake
COPY --chmod=0755 infrastructure/docker/airflow-init.sh /usr/local/bin/airflow-init
COPY infrastructure/docker/fhir-warmup.json /opt/healthlake/fhir-warmup.json

# Read-only for the runtime user: ADD of a URL can leave /opt/healthlake without the execute bit for others
# (found by the first CI image build: "Unable to access jarfile" as uid 50000).
RUN set -eux; mkdir -p /data/landing /data/lake /data/work /data/artifacts; \
    chown -R 50000:0 /data; chmod -R 0770 /data; \
    find /opt/healthlake -type d -exec chmod 0755 {} +; find /opt/healthlake -type f -exec chmod a+r,go-w {} +; \
    ls -ld /opt/healthlake /opt/healthlake/validator_cli.jar /opt/healthlake/synthea.jar

ENV HEALTHLAKE_CONFIG_DIR=/opt/healthlake/config \
    HEALTHLAKE_MIGRATIONS_DIR=/opt/healthlake/migrations \
    HEALTHLAKE_DBT_PROJECT_DIR=/opt/healthlake/dbt \
    HEALTHLAKE_DBT_BIN=/opt/dbt-venv/bin/dbt \
    HEALTHLAKE_HL7_VALIDATOR_JAR=/opt/healthlake/validator_cli.jar \
    HEALTHLAKE_SYNTHEA_JAR=/opt/healthlake/synthea.jar \
    HEALTHLAKE_CLI=/usr/local/bin/healthlake \
    HEALTHLAKE_LANDING_DIR=/data/landing HEALTHLAKE_LAKE_DIR=/data/lake \
    HEALTHLAKE_WORK_DIR=/data/work HEALTHLAKE_ARTIFACTS_DIR=/data/artifacts

USER airflow
# Pre-load FHIR packages (R4 core, terminology, US Core) so validation later runs offline with -tx n/a.
RUN { java -jar /opt/healthlake/validator_cli.jar /opt/healthlake/fhir-warmup.json -version 4.0.1 -tx n/a \
        -output /tmp/warmup-result.json > /tmp/warmup.log 2>&1 \
      && ls /home/airflow/.fhir/packages | grep -q 'hl7.fhir.r4.core#4.0.1'; } \
    || { echo "FHIR warm-up failed; validator log tail:"; tail -n 40 /tmp/warmup.log; \
         grep -m1 'Package Cache' /tmp/warmup.log || true; id; exit 1; } \
    && rm -f /tmp/warmup*
RUN healthlake --version && /opt/dbt-venv/bin/dbt --version > /dev/null && airflow version
