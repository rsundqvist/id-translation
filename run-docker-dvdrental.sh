#!/bin/bash

set -eax

docker compose -v -f tests/dvdrental/docker/docker-compose.yml down

docker compose -p id-translation-tests -f tests/dvdrental/docker/docker-compose.yml --profile=$"${1}" up --wait
printf "\033[92mSleeping for 10 sec before verification..\033[0m\n"

sleep 10
docker run --network=host --rm rsundqvist/sakila-preload:db-tests
