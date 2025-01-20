#!/bin/bash

# https://github.com/microsoft/mssql-docker/issues/868#issuecomment-2374092454
set -eax

docker build images/mssql/ -t rsundqvist/sakila-preload:mssql --no-cache
docker build images/mysql/ -t rsundqvist/sakila-preload:mysql --no-cache
docker build images/postgresql/ -t rsundqvist/sakila-preload:postgres --no-cache
docker build . -t rsundqvist/sakila-preload:db-tests --no-cache