#!/bin/bash

set -eax

if command -v docker >/dev/null; then
  docker=docker
else
  docker=podman
fi

file=tests/dvdrental/docker/docker-compose.yml

$docker compose -p id-translation-tests -f $file down --volumes --remove-orphans

$docker compose -p id-translation-tests -f $file --profile=$"${1}" up -d --wait
printf "\033[92mSleeping for 10 sec before verification..\033[0m\n"

sleep 10
$docker run --network=host --rm docker.io/rsundqvist/sakila-preload:db-tests
