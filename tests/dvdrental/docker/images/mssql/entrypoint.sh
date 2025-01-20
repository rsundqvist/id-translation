#!/bin/bash

# set -eax  # Doesn't work - exit code is 255

/bin/bash configure-db.sh &
/opt/mssql/bin/sqlservr
exit 0
