ARG BASE_IMAGE=mysql:debian

FROM debian:latest AS download
    RUN apt-get update && apt-get install wget unzip --yes

    RUN wget https://downloads.mysql.com/docs/sakila-db.zip
    RUN unzip sakila-db.zip

    RUN mkdir /sql-sources/
    RUN mv sakila-db/sakila-schema.sql /sql-sources/0_schema.sql
    RUN mv sakila-db/sakila-data.sql /sql-sources/1_data.sql
    COPY uuid.sql /sql-sources/2_uuid.sql

FROM $BASE_IMAGE AS source
    ENV MYSQL_ROOT_PASSWORD="Sofia123!"
    ENV MYSQL_DATABASE="sakila"

    COPY --from=download /sql-sources/ /docker-entrypoint-initdb.d/
    RUN ["sed", "-i", "s/exec \"$@\"/echo \"skipping...\"/", "/usr/local/bin/docker-entrypoint.sh"]

    RUN ["/usr/local/bin/docker-entrypoint.sh", "mysqld"]

FROM $BASE_IMAGE
    COPY --from=source /var/lib/mysql/ /var/lib/mysql/
