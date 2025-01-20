ARG BASE_IMAGE=postgres:17-alpine

FROM debian:latest AS download
    RUN apt-get update && apt-get install wget --yes

    RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/postgres-sakila-db/postgres-sakila-schema.sql
    RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/postgres-sakila-db/postgres-sakila-insert-data.sql

    RUN mkdir /sql-sources/
    RUN mv postgres-sakila-schema.sql /sql-sources/0_schema.sql
    RUN mv postgres-sakila-insert-data.sql /sql-sources/1_data.sql
    COPY uuid.sql /sql-sources/uuid.sql

FROM $BASE_IMAGE AS source
    ENV POSTGRES_PASSWORD="Sofia123!"
    ENV POSTGRES_DB="sakila"

    COPY --from=download /sql-sources/ /docker-entrypoint-initdb.d/
    RUN ["sed", "-i", "s/exec \"$@\"/echo \"skipping...\"/", "/usr/local/bin/docker-entrypoint.sh"]

    RUN ["/usr/local/bin/docker-entrypoint.sh", "postgres"]

FROM $BASE_IMAGE
    COPY --from=source $PGDATA $PGDATA
