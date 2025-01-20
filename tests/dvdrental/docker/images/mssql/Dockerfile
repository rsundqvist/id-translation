ARG BASE_IMAGE=mcr.microsoft.com/mssql/server:2022-CU16-ubuntu-22.04

FROM debian:latest AS download
    RUN apt-get update && apt-get install wget --yes

    RUN mkdir /sql-sources/
    RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/sql-server-sakila-db/sql-server-sakila-schema.sql
    RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/sql-server-sakila-db/sql-server-sakila-insert-data.sql
    RUN mv sql-server-sakila-schema.sql /sql-sources/0_schema.sql
    RUN mv sql-server-sakila-insert-data.sql /sql-sources/1_data.sql
    COPY uuid.sql /sql-sources/2_uuid.sql

FROM $BASE_IMAGE AS source
    ENV MSSQL_SA_PASSWORD="Sofia123!"
    ENV ACCEPT_EULA="Y"

    COPY --from=download /sql-sources/ /sql-sources/
    COPY entrypoint.sh configure-db.sh /sql-sources/


    WORKDIR /sql-sources/
    RUN /sql-sources/entrypoint.sh

FROM $BASE_IMAGE
    ENV MSSQL_SA_PASSWORD="Sofia123!"
    ENV ACCEPT_EULA="Y"

    COPY --from=source /var/opt/mssql/ /var/opt/mssql/


    CMD ["/opt/mssql/bin/sqlservr"]
