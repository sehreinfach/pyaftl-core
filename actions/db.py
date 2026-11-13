import os
import sqlite3
from datetime import datetime
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "db.sqlite3")


def log_job_start(host=None, group=None, playbook=None):
    """
    writes one line to table "runner-log" when a job is started
    the table is created by data/init.sql
    :param host: host limit of the run (comma separated), or None
    :param group: inventory group of the run, or None
    :param playbook: playbook name of the run, or None
    """
    timestamp = datetime.now().isoformat(timespec="seconds")
    with closing(sqlite3.connect(DB_PATH)) as con, con:
        con.execute(
            'INSERT INTO "runner-log" ("timestamp", "host", "group_name", "playbook") VALUES (?, ?, ?, ?)',
            (timestamp, host, group, playbook),
        )
