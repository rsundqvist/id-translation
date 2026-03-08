#!/bin/bash
set -e

echo "---------- run-invocations.sh -----------"
echo "1/7: Clean ------------------------------"
uv run inv clean
echo "2/7: Format code ------------------------"
uv run inv format
echo "3/7: Lint -------------------------------"
uv run inv lint
echo "4/7: Typecheck (mypy) -------------------"
uv run inv mypy
echo "5/7: Test -------------------------------"
uv run inv tests
echo "6/7: Coverage report --------------------"
uv run inv coverage -f=html
echo "7/7: Generate docs ----------------------"
uv run inv docs
echo "---------------- Finished ---------------"
