#!/bin/bash

sleep 15

/opt/mssql-tools/bin/sqlcmd -S localhost -e -l 60 -U sa -P $MSSQL_SA_PASSWORD -i ./sql-sources/0_schema.sql
/opt/mssql-tools/bin/sqlcmd -S localhost    -l 15 -U sa -P $MSSQL_SA_PASSWORD -d sakila -i ./sql-sources/1_data.sql
/opt/mssql-tools/bin/sqlcmd -S localhost -e -l 15 -U sa -P $MSSQL_SA_PASSWORD -Q "SHUTDOWN WITH NOWAIT;"
