#!/bin/bash

/bin/bash configure-db.sh &
/opt/mssql/bin/sqlservr
exit 0
