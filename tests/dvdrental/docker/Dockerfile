FROM python:3.10-slim-buster

COPY credentials.yml .

COPY tests/requirements.txt .
RUN pip install -r requirements.txt

COPY tests/ tests/
ENTRYPOINT python -m pytest tests/test_dialects.py --color=yes
