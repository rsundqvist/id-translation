#!/bin/bash
set -e

echo "---------- run-invocations.sh -----------"
echo "1/7: Clean ------------------------------"
poetry run inv clean
echo "2/7: Format code ------------------------"
poetry run inv format
echo "3/7: Lint -------------------------------"
poetry run inv lint
echo "4/7: Typecheck (mypy) -------------------"
poetry run inv mypy
echo "5/7: Test -------------------------------"
poetry run inv tests
echo "6/7: Coverage report --------------------"
poetry run inv coverage -f=html
echo "7/7: Generate docs ----------------------"
poetry run inv docs
echo "---------------- Finished ---------------"
