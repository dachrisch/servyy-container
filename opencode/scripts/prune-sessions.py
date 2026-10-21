#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Prune old OpenCode V2 sessions, stale tool output, and stale checkpoint
snapshots.

Runs inside the opencode.web container via an Ofelia job-exec label
(schedule: 0 4 * * *). Deletes sessions older than OPENCODE_PRUNE_HOURS
(default 24) from the V2 `session_v2` table together with all dependent
rows, purges tool-output files past retention, removes checkpoint snapshot
repos untouched since before that retention window, and vacuums the
database only when rows were actually deleted. Designed to be idempotent
and to never interfere with the running web server: it uses a generous
busy_timeout and logs a one-line summary that ends up in
`docker logs portainer.ofelia`.

After an in-place V1 -> V2 migration the legacy V1 tables (`session`,
`part`, `message`, `todo`, `session_share`, `session_input`,
`session_context_epoch`) still sit in the file, dead weight that V2 never
reads. They are cleaned as a defensive extra when present; a fresh V2
install has none of them, so the cleanup is skipped there. Pruning the V2
tables is what actually bounds database growth.
"""

import os
import shutil
import sqlite3
import sys
import time

DB_PATH = os.environ.get("OPENCODE_DB", "/root/.local/share/opencode/opencode.db")
TOOL_OUTPUT_DIR = os.environ.get("OPENCODE_TOOL_OUTPUT", "/root/.local/share/opencode/tool-output")
SNAPSHOT_DIR = os.environ.get("OPENCODE_SNAPSHOT_DIR", "/root/.local/share/opencode/snapshot")
RETENTION_HOURS = float(os.environ.get("OPENCODE_PRUNE_HOURS", "24"))

SESSION_TABLE = "session_v2"

# Tables that reference a live session and must lose their rows before the
# session row itself is deleted.
V2_DEPENDENT_TABLES = [
    ("session_message", "session_id"),
    ("session_inbox", "session_id"),
    ("session_pending", "session_id"),
    ("instruction_entry", "session_id"),
    ("instruction_state", "session_id"),
    ("event", "aggregate_id"),
    ("event_sequence", "aggregate_id"),
]

# Left behind by the V1 -> V2 migration, keyed by the legacy `session` table.
LEGACY_DEPENDENT_TABLES = [
    ("part", "session_id"),
    ("message", "session_id"),
    ("todo", "session_id"),
    ("session_share", "session_id"),
    ("session_input", "session_id"),
    ("session_context_epoch", "session_id"),
]
LEGACY_SESSION_TABLE = "session"


def log(message):
    """Emit a timestamped line for Ofelia's log output."""
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def _existing_tables(con):
    """Return the set of table names present in the database file."""
    return {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _delete_rows(con, table, column, values, counts):
    """Delete `values` from table.column, recording a non-zero row count."""
    if not values:
        return 0
    placeholders = ",".join("?" * len(values))
    deleted = con.execute(
        "DELETE FROM %s WHERE %s IN (%s)" % (table, column, placeholders), values
    ).rowcount
    if deleted > 0:
        counts.append("%s=%d" % (table, deleted))
    return deleted


def prune_sessions(con, cutoff):
    """Delete sessions older than cutoff (ms epoch) and all dependent rows.

    Returns the number of distinct session rows deleted (V2 plus legacy-only
    V1 leftovers); anything above zero means the caller should vacuum.
    """
    tables = _existing_tables(con)
    if SESSION_TABLE not in tables:
        # A missing session_v2 means the schema is not what this script
        # expects (e.g. an un-migrated V1 database). Fail loudly instead of
        # logging a successful no-op forever.
        raise sqlite3.Error("table %s not found; database is not an OpenCode V2 schema" % SESSION_TABLE)

    session_ids = [
        row[0]
        for row in con.execute(
            "SELECT id FROM %s WHERE time_created < ?" % SESSION_TABLE, (cutoff,)
        )
    ]

    # Legacy V1 rows are only cleaned for sessions that are not still live in
    # V2, so the defensive cleanup can never touch a current session.
    legacy_ids = []
    if LEGACY_SESSION_TABLE in tables:
        surviving = {
            row[0]
            for row in con.execute(
                "SELECT id FROM %s WHERE time_created >= ?" % SESSION_TABLE, (cutoff,)
            )
        }
        legacy_ids = [
            row[0]
            for row in con.execute(
                "SELECT id FROM %s WHERE time_created < ?" % LEGACY_SESSION_TABLE, (cutoff,)
            )
            if row[0] not in surviving
        ]

    if not session_ids and not legacy_ids:
        log("no sessions older than %.0fh, nothing to do" % RETENTION_HOURS)
        return 0

    counts = []
    con.execute("BEGIN")
    for table, column in V2_DEPENDENT_TABLES:
        if table in tables:
            _delete_rows(con, table, column, session_ids, counts)
    _delete_rows(con, SESSION_TABLE, "id", session_ids, counts)

    # Sessions that only ever existed in the legacy tables (V1 rows the
    # migration left behind) are counted once, not twice: the same id can
    # appear in both tables.
    if legacy_ids:
        for table, column in LEGACY_DEPENDENT_TABLES:
            if table in tables:
                _delete_rows(con, table, column, legacy_ids, counts)
        _delete_rows(con, LEGACY_SESSION_TABLE, "id", legacy_ids, counts)
    con.commit()
    pruned_ids = set(session_ids)
    pruned = len(session_ids) + sum(1 for session_id in legacy_ids if session_id not in pruned_ids)
    log("pruned %d sessions: %s" % (pruned, ", ".join(counts) or "no dependent rows"))
    return pruned


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


def _newest_mtime(path):
    """Return the mtime (epoch seconds) of the most recently touched file under path."""
    newest = 0.0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                pass
    return newest


def prune_snapshots(cutoff):
    """Remove checkpoint snapshot repos (each a self-contained git repo under
    SNAPSHOT_DIR/<project>/<repo>/) untouched since before cutoff (ms epoch)."""
    if not os.path.isdir(SNAPSHOT_DIR):
        return 0
    removed = 0
    for project in os.listdir(SNAPSHOT_DIR):
        project_path = os.path.join(SNAPSHOT_DIR, project)
        if not os.path.isdir(project_path):
            continue
        for repo in os.listdir(project_path):
            repo_path = os.path.join(project_path, repo)
            if not os.path.isdir(repo_path):
                continue
            try:
                if _newest_mtime(repo_path) < cutoff / 1000:
                    shutil.rmtree(repo_path)
                    removed += 1
            except OSError as error:
                log("could not remove snapshot %s/%s (%s)" % (project, repo, error))
        try:
            if not os.listdir(project_path):
                os.rmdir(project_path)
        except OSError:
            pass
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
        removed_snapshots = prune_snapshots(cutoff)
        if removed_snapshots:
            log("pruned %d snapshot checkpoint repos" % removed_snapshots)
    except sqlite3.Error as error:
        log("database error, aborted: %s" % error)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
