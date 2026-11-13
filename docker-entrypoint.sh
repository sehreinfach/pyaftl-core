#!/bin/sh
set -e

# create the sqlite database from data/init.sql on first start
if [ ! -f data/db.sqlite3 ]; then
    python3 -c "import sqlite3; c = sqlite3.connect('data/db.sqlite3'); c.executescript(open('data/init.sql').read()); c.close()"
    echo "initialized data/db.sqlite3"
fi

exec "$@"
