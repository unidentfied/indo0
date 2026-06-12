FROM postgis/postgis:16-3.4

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gnupg \
        lsb-release \
        wget && \
    echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/timescaledb.list && \
    wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | apt-key add - && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        timescaledb-2-postgresql-16 \
        timescaledb-toolkit-postgresql-16 && \
    apt-get purge -y gnupg lsb-release wget && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

RUN echo "shared_preload_libraries = 'timescaledb'" >> /usr/share/postgresql/postgresql.conf.sample

# Ensure TimescaleDB extension is created on first init
RUN echo "CREATE EXTENSION IF NOT EXISTS timescaledb;" >> /docker-entrypoint-initdb.d/001_init.sql

ENV POSTGRES_USER=sindio_user
ENV POSTGRES_PASSWORD=sindio_pass
ENV POSTGRES_DB=sindio

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} || exit 1
