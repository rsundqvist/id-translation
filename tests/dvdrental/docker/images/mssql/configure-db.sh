#!/bin/bash

set -eax

sleep 15

# https://github.com/microsoft/mssql-docker/issues/892
/opt/mssql-tools18/bin/sqlcmd -C -Slocalhost -e -l 60 -U sa -P "$MSSQL_SA_PASSWORD"           -i 0_schema.sql
/opt/mssql-tools18/bin/sqlcmd -C -Slocalhost    -l 15 -U sa -P "$MSSQL_SA_PASSWORD" -d sakila -i 1_data.sql
/opt/mssql-tools18/bin/sqlcmd -C -Slocalhost    -l 15 -U sa -P "$MSSQL_SA_PASSWORD" -d sakila -i 2_uuid.sql
/opt/mssql-tools18/bin/sqlcmd -C -Slocalhost -e -l 15 -U sa -P "$MSSQL_SA_PASSWORD" -Q "SHUTDOWN WITH NOWAIT;"
