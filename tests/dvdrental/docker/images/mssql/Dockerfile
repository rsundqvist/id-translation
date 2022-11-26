FROM mcr.microsoft.com/mssql/server:2019-latest AS source

# USER root

RUN mkdir -p /usr/config
WORKDIR /usr/config


RUN mkdir ./sql-sources/
RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/sql-server-sakila-db/sql-server-sakila-schema.sql
RUN wget --quiet https://raw.githubusercontent.com/jOOQ/sakila/main/sql-server-sakila-db/sql-server-sakila-insert-data.sql
RUN mv sql-server-sakila-schema.sql ./sql-sources/0_schema.sql
RUN mv sql-server-sakila-insert-data.sql ./sql-sources/1_data.sql

ENV MSSQL_SA_PASSWORD "Sofia123!"
ENV ACCEPT_EULA "Y"

COPY . ./
RUN ./entrypoint.sh

FROM mcr.microsoft.com/mssql/server:2019-latest
COPY --from=source /var/opt/mssql/ /var/opt/mssql/

CMD ["/opt/mssql/bin/sqlservr"]
