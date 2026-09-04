#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Prune old opencode sessions and stale tool output.

Runs inside the opencode.web container via an Ofelia job-exec label
(schedule: 0 4 * * *). Deletes sessions older than OPENCODE_PRUNE_HOURS
(default 24) together with all dependent rows, purges tool-output files
past retention, and vacuums the database only when rows were actually
deleted. Designed to be idempotent and to never interfere with the
running web server: it uses a generous busy_timeout and logs a one-line
summary that ends up in `docker logs portainer.ofelia`.
"""

import os
import sqlite3
import sys
import time

DB_PATH = os.environ.get("OPENCODE_DB", "/root/.local/share/opencode/opencode.db")
TOOL_OUTPUT_DIR = os.environ.get("OPENCODE_TOOL_OUTPUT", "/root/.local/share/opencode/tool-output")
RETENTION_HOURS = float(os.environ.get("OPENCODE_PRUNE_HOURS", "24"))

DEPENDENT_TABLES = [
    ("part", "session_id"),
    ("message", "session_id"),
    ("session_message", "session_id"),
    ("session_input", "session_id"),
    ("session_context_epoch", "session_id"),
    ("todo", "session_id"),
    ("session_share", "session_id"),
    ("event", "aggregate_id"),
    ("event_sequence", "aggregate_id"),
]


def log(message):
    """Emit a timestamped line for Ofelia's log output."""
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def prune_sessions(con, cutoff):
    """Delete sessions older than cutoff (ms epoch) and all dependent rows."""
    session_ids = [row[0] for row in con.execute("SELECT id FROM session WHERE time_created < ?", (cutoff,))]
    if not session_ids:
        log("no sessions older than %.0fh, nothing to do" % RETENTION_HOURS)
        return 0
    placeholders = ",".join("?" * len(session_ids))
    counts = []
    con.execute("BEGIN")
    for table, column in DEPENDENT_TABLES:
        cursor = con.execute("DELETE FROM %s WHERE %s IN (%s)" % (table, column, placeholders), session_ids)
        if cursor.rowcount > 0:
            counts.append("%s=%d" % (table, cursor.rowcount))
    session_count = con.execute(
        "DELETE FROM session WHERE id IN (%s)" % placeholders, session_ids
    ).rowcount
    con.commit()
    log("pruned %d sessions: %s" % (session_count, ", ".join(counts)))
    return session_count


def vacuum(con):
    """Reclaim disk space; tolerate lock contention with the web server."""
    try:
        con.execute("VACUUM")
        log("vacuum ok")
    except sqlite3.Error as error:
        log("vacuum skipped (%s)" % error)


def prune_tool_output(cutoff):
    """Remove tool-output files older than cutoff, returning the count."""
    if not os.path.isdir(TOOL_OUTPUT_DIR):
        return 0
    removed = 0
    for name in os.listdir(TOOL_OUTPUT_DIR):
        path = os.path.join(TOOL_OUTPUT_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff / 1000:
                os.remove(path)
                removed += 1
        except OSError as error:
            log("could not remove %s (%s)" % (name, error))
    return removed


def main():
    """Entry point; returns a process exit code."""
    cutoff = int((time.time() - RETENTION_HOURS * 3600) * 1000)
    if not os.path.exists(DB_PATH):
        log("database not found at %s, skipping" % DB_PATH)
        return 0
    try:
        con = sqlite3.connect(DB_PATH, timeout=60)
    except sqlite3.Error as error:
        log("could not open database: %s" % error)
        return 1
    try:
        con.execute("PRAGMA busy_timeout=60000")
        deleted = prune_sessions(con, cutoff)
        if deleted:
            vacuum(con)
        removed = prune_tool_output(cutoff)
        if removed:
            log("pruned %d tool-output files" % removed)
    except sqlite3.Error as error:
        log("database error, aborted: %s" % error)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
