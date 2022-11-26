#!/bin/bash

docker compose -f tests/dvdrental/docker/docker-compose.yml up --wait
echo "Sleeping for 10 sec before verification.."
sleep 10
docker run --network=host --rm rsundqvist/sakila-preload:db-tests
