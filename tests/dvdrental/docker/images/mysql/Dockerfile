FROM mysql:debian AS source

RUN ["sed", "-i", "s/exec \"$@\"/echo \"skipping...\"/", "/usr/local/bin/docker-entrypoint.sh"]

RUN apt-get update && apt-get install wget unzip --yes
RUN wget https://downloads.mysql.com/docs/sakila-db.zip
RUN unzip sakila-db.zip
RUN mv sakila-db/sakila-schema.sql /docker-entrypoint-initdb.d/0_schema.sql
RUN mv sakila-db/sakila-data.sql /docker-entrypoint-initdb.d/1_data.sql

ENV MYSQL_ROOT_PASSWORD="Sofia123!"
ENV MYSQL_DATABASE="sakila"

RUN ["/usr/local/bin/docker-entrypoint.sh", "mysqld", "--datadir", "/data"]

FROM mysql:debian
COPY --from=source /data /var/lib/mysql
