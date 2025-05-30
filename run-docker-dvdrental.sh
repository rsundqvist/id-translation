#!/bin/bash

set -eax

docker compose -v -f tests/dvdrental/docker/docker-compose.yml down
docker compose -p dvdrental -f tests/dvdrental/docker/docker-compose.yml up --wait
echo "Sleeping for 10 sec before verification.."
sleep 10
docker run --network=host --rm rsundqvist/sakila-preload:db-tests
