CREATE TABLE IF NOT EXISTS "host_group" (
    "name"	TEXT NOT NULL UNIQUE,
    "description"	TEXT,
    PRIMARY KEY("name")
);

CREATE TABLE IF NOT EXISTS "host_list" (
    "host_name"	TEXT NOT NULL UNIQUE,
    "host_addr"	TEXT NOT NULL UNIQUE,
    "host_group"	TEXT NOT NULL,
    "active"	INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY("host_name")
);

CREATE TABLE IF NOT EXISTS "runner-log" (
    "id"	INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "timestamp"	TEXT NOT NULL,
    "host"	TEXT,
    "group_name"	TEXT,
    "playbook"	TEXT
);
