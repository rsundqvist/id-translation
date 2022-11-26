FROM postgres:latest AS source

RUN apt-get update && apt-get install wget --yes

# pagila changes the dates and a bunch of other things; can't check equality
#RUN git clone https://github.com/devrimgunduz/pagila.git

RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/postgres-sakila-db/postgres-sakila-schema.sql
RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/postgres-sakila-db/postgres-sakila-insert-data.sql
RUN mv ./postgres-sakila-schema.sql  /docker-entrypoint-initdb.d/0_schema.sql
RUN mv ./postgres-sakila-insert-data.sql /docker-entrypoint-initdb.d/1_data.sql

RUN ["sed", "-i", "s/exec \"$@\"/echo \"skipping...\"/", "/usr/local/bin/docker-entrypoint.sh"]

ENV POSTGRES_DB="sakila"
ENV POSTGRES_PASSWORD="Sofia123!"

RUN ["/usr/local/bin/docker-entrypoint.sh", "postgres"]

FROM postgres:latest
COPY --from=source $PGDATA $PGDATA
