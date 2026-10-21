#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Tests for prune-sessions.py against the OpenCode V2 SQLite schema.

The script lives next to this file as ``prune-sessions.py`` (a dash in the
name), so it is loaded through importlib.  It reads its configuration from
the environment at import time, hence OPENCODE_DB is pointed at a throwaway
path *before* the module is executed: no test can ever reach the real
database even if it accidentally calls main().
"""

import importlib.util
import os
import sqlite3
import tempfile
import time
import unittest

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prune-sessions.py")

_ENV_DIR = tempfile.mkdtemp(prefix="prune-test-env-")
os.environ["OPENCODE_DB"] = os.path.join(_ENV_DIR, "absent.db")
os.environ["OPENCODE_TOOL_OUTPUT"] = os.path.join(_ENV_DIR, "tool-output")
os.environ["OPENCODE_SNAPSHOT_DIR"] = os.path.join(_ENV_DIR, "snapshot")

_spec = importlib.util.spec_from_file_location("prune_sessions", _SCRIPT)
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)

# (table, session key column) - dependent tables of the live V2 session table.
V2_DEPENDENTS = {
    "session_message": "session_id",
    "session_inbox": "session_id",
    "session_pending": "session_id",
    "instruction_entry": "session_id",
    "instruction_state": "session_id",
    "event": "aggregate_id",
    "event_sequence": "aggregate_id",
}

# Tables left behind by an in-place V1 -> V2 migration; V2 never reads them.
LEGACY_DEPENDENTS = {
    "part": "session_id",
    "message": "session_id",
    "todo": "session_id",
    "session_share": "session_id",
    "session_input": "session_id",
    "session_context_epoch": "session_id",
}

V2_SCHEMA = [
    "CREATE TABLE project (id text PRIMARY KEY, worktree text NOT NULL, time_created integer NOT NULL)",
    """CREATE TABLE session_v2 (
        id text PRIMARY KEY,
        project_id text NOT NULL,
        workspace_id text,
        parent_id text,
        slug text NOT NULL,
        directory text NOT NULL,
        title text,
        version text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        time_archived integer
    )""",
    """CREATE TABLE session_message (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        type text NOT NULL,
        seq integer NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL
    )""",
    """CREATE TABLE session_inbox (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        type text NOT NULL,
        payload text NOT NULL,
        delivery text NOT NULL,
        enqueued_seq integer NOT NULL,
        time_created integer NOT NULL
    )""",
    """CREATE TABLE session_pending (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        type text NOT NULL,
        data text NOT NULL,
        delivery text,
        admitted_seq integer NOT NULL,
        time_created integer NOT NULL
    )""",
    "CREATE TABLE event_sequence (aggregate_id text PRIMARY KEY, seq integer NOT NULL, owner_id text)",
    """CREATE TABLE event (
        id text PRIMARY KEY,
        aggregate_id text NOT NULL,
        seq integer NOT NULL,
        type text NOT NULL,
        data text NOT NULL,
        created integer DEFAULT 0 NOT NULL
    )""",
    """CREATE TABLE instruction_entry (
        session_id text NOT NULL,
        key text NOT NULL,
        value text,
        removed integer DEFAULT 0 NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        PRIMARY KEY (session_id, key)
    )""",
    "CREATE TABLE instruction_blob (hash text PRIMARY KEY, value text)",
    """CREATE TABLE instruction_state (
        session_id text PRIMARY KEY,
        epoch_start integer NOT NULL,
        through_seq integer NOT NULL,
        initial_values text NOT NULL,
        current_values text NOT NULL
    )""",
]

LEGACY_SCHEMA = [
    """CREATE TABLE session (
        id text PRIMARY KEY,
        project_id text NOT NULL,
        slug text NOT NULL,
        directory text NOT NULL,
        title text NOT NULL,
        version text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL
    )""",
    """CREATE TABLE message (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL
    )""",
    """CREATE TABLE part (
        id text PRIMARY KEY,
        message_id text NOT NULL,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL
    )""",
    """CREATE TABLE todo (
        session_id text NOT NULL,
        content text NOT NULL,
        status text NOT NULL,
        priority text NOT NULL,
        position integer NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        PRIMARY KEY (session_id, position)
    )""",
    """CREATE TABLE session_share (
        session_id text PRIMARY KEY,
        id text NOT NULL,
        secret text NOT NULL,
        url text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL
    )""",
    """CREATE TABLE session_input (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        data text NOT NULL
    )""",
    """CREATE TABLE session_context_epoch (
        session_id text PRIMARY KEY,
        epoch_start integer NOT NULL,
        time_created integer NOT NULL
    )""",
]


def create_schema(con, legacy=True):
    for statement in V2_SCHEMA + (LEGACY_SCHEMA if legacy else []):
        con.execute(statement)


def seed_session(con, session_id, created, legacy=True):
    """Insert one session with dependent rows in every V2 (and legacy) table."""
    con.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated)"
        " VALUES (?, 'prj_test', ?, '/tmp/project', ?, '2.1.2', ?, ?)",
        (session_id, "slug-" + session_id, "title " + session_id, created, created),
    )
    con.execute(
        "INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data)"
        " VALUES (?, ?, 'text', 1, ?, ?, '{}')",
        (session_id + "_msg", session_id, created, created),
    )
    con.execute(
        "INSERT INTO session_inbox (id, session_id, type, payload, delivery, enqueued_seq, time_created)"
        " VALUES (?, ?, 'user', '{}', 'immediate', 1, ?)",
        (session_id + "_inbox", session_id, created),
    )
    con.execute(
        "INSERT INTO session_pending (id, session_id, type, data, delivery, admitted_seq, time_created)"
        " VALUES (?, ?, 'tool', '{}', 'immediate', 1, ?)",
        (session_id + "_pending", session_id, created),
    )
    con.execute(
        "INSERT INTO instruction_entry (session_id, key, value, removed, time_created, time_updated)"
        " VALUES (?, 'instructions', 'v', 0, ?, ?)",
        (session_id, created, created),
    )
    con.execute(
        "INSERT INTO instruction_state (session_id, epoch_start, through_seq, initial_values, current_values)"
        " VALUES (?, 0, 0, '{}', '{}')",
        (session_id,),
    )
    con.execute(
        "INSERT INTO event_sequence (aggregate_id, seq, owner_id) VALUES (?, 1, ?)",
        (session_id, session_id),
    )
    con.execute(
        "INSERT INTO event (id, aggregate_id, seq, type, data, created)"
        " VALUES (?, ?, 1, 'session.updated.1', '{}', ?)",
        (session_id + "_evt", session_id, created),
    )
    if legacy:
        con.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES (?, 'prj_test', ?, '/tmp/project', ?, '1.19.3', ?, ?)",
            (session_id, "slug-" + session_id, "title " + session_id, created, created),
        )
        con.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, '{}')",
            (session_id + "_legacy_msg", session_id, created, created),
        )
        con.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, '{}')",
            (session_id + "_legacy_part", session_id + "_legacy_msg", session_id, created, created),
        )
        con.execute(
            "INSERT INTO todo (session_id, content, status, priority, position, time_created, time_updated)"
            " VALUES (?, 'c', 'pending', 'high', 0, ?, ?)",
            (session_id, created, created),
        )
        con.execute(
            "INSERT INTO session_share (session_id, id, secret, url, time_created, time_updated)"
            " VALUES (?, ?, 's', 'https://example.invalid', ?, ?)",
            (session_id, "share-" + session_id, created, created),
        )
        con.execute(
            "INSERT INTO session_input (id, session_id, time_created, data) VALUES (?, ?, ?, '{}')",
            (session_id + "_input", session_id, created),
        )
        con.execute(
            "INSERT INTO session_context_epoch (session_id, epoch_start, time_created) VALUES (?, 0, ?)",
            (session_id, created),
        )


def count_rows(con, table, column, value):
    return con.execute(
        "SELECT count(*) FROM %s WHERE %s = ?" % (table, column), (value,)
    ).fetchone()[0]


class PruneSessionsTest(unittest.TestCase):
    """The old session must disappear from session_v2 and every dependent table."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prune-test-")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "opencode.db")
        self.con = sqlite3.connect(self.db_path)
        self.addCleanup(self.con.close)
        create_schema(self.con, legacy=True)
        self.now_ms = int(time.time() * 1000)
        self.cutoff = self.now_ms - 3600_000
        self.old = "ses_old"
        self.fresh = "ses_fresh"
        seed_session(self.con, self.old, self.cutoff - 30 * 86400_000)
        seed_session(self.con, self.fresh, self.now_ms)
        self.con.commit()

    def test_old_session_is_removed_from_session_v2(self):
        deleted = prune.prune_sessions(self.con, self.cutoff)
        # One session, present in both session_v2 and the legacy table: it is
        # reported once, not twice.
        self.assertEqual(deleted, 1)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0],
            0,
            "old session still present in session_v2 (V1 table was pruned instead)",
        )
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.fresh,)).fetchone()[0], 1
        )

    def test_old_dependents_are_removed(self):
        prune.prune_sessions(self.con, self.cutoff)
        for table, column in V2_DEPENDENTS.items():
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, column, self.old),
                    0,
                    "%s still holds rows for the pruned session" % table,
                )

    def test_fresh_session_and_dependents_survive(self):
        prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.fresh,)).fetchone()[0], 1
        )
        for table, column in V2_DEPENDENTS.items():
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, column, self.fresh),
                    1,
                    "%s lost rows of the fresh session" % table,
                )

    def test_legacy_tables_are_cleaned_for_dead_sessions(self):
        """Legacy V1 rows are dead weight after the migration and get removed."""
        prune.prune_sessions(self.con, self.cutoff)
        for table, column in LEGACY_DEPENDENTS.items():
            with self.subTest(table=table):
                self.assertEqual(count_rows(self.con, table, column, self.old), 0)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session WHERE id = ?", (self.old,)).fetchone()[0], 0
        )

    def test_legacy_rows_of_fresh_session_survive(self):
        prune.prune_sessions(self.con, self.cutoff)
        for table, column in LEGACY_DEPENDENTS.items():
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, column, self.fresh),
                    1,
                    "%s lost rows of the fresh session" % table,
                )
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session WHERE id = ?", (self.fresh,)).fetchone()[0], 1
        )

    def test_second_run_is_a_no_op(self):
        first = prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(first, 1)
        snapshot = {
            table: self.con.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
            for table in list(V2_DEPENDENTS) + list(LEGACY_DEPENDENTS) + ["session_v2", "session"]
        }
        second = prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(second, 0)
        for table, before in snapshot.items():
            with self.subTest(table=table):
                self.assertEqual(self.con.execute("SELECT count(*) FROM %s" % table).fetchone()[0], before)

    def test_legacy_only_old_session_is_cleaned_and_counted(self):
        """V1 rows the migration never carried over are still dead weight."""
        old_only = "ses_legacy_only"
        created = self.cutoff - 60 * 86400_000
        self.con.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES (?, 'prj_test', 'slug', '/tmp/project', 't', '1.19.3', ?, ?)",
            (old_only, created, created),
        )
        self.con.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, '{}')",
            (old_only + "_msg", old_only, created, created),
        )
        self.con.execute(
            "INSERT INTO todo (session_id, content, status, priority, position, time_created, time_updated)"
            " VALUES (?, 'c', 'pending', 'high', 0, ?, ?)",
            (old_only, created, created),
        )
        self.con.commit()

        self.assertEqual(prune.prune_sessions(self.con, self.cutoff), 2)
        self.assertEqual(self.con.execute("SELECT count(*) FROM session WHERE id = ?", (old_only,)).fetchone()[0], 0)
        self.assertEqual(count_rows(self.con, "message", "session_id", old_only), 0)
        self.assertEqual(count_rows(self.con, "todo", "session_id", old_only), 0)

    def test_main_returns_zero_and_vacuums(self):
        prune.DB_PATH = self.db_path
        prune.RETENTION_HOURS = 1.0
        self.addCleanup(setattr, prune, "DB_PATH", os.environ["OPENCODE_DB"])
        self.addCleanup(setattr, prune, "RETENTION_HOURS", 24.0)
        self.con.commit()
        self.assertEqual(prune.main(), 0)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0], 0
        )


class FreshInstallTest(unittest.TestCase):
    """A fresh V2 install has none of the legacy tables; pruning must not care."""

    def test_prune_without_legacy_tables(self):
        tmp = tempfile.TemporaryDirectory(prefix="prune-fresh-")
        self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(os.path.join(tmp.name, "opencode.db"))
        self.addCleanup(con.close)
        create_schema(con, legacy=False)
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - 3600_000
        seed_session(con, "ses_old", cutoff - 30 * 86400_000, legacy=False)
        seed_session(con, "ses_fresh", now_ms, legacy=False)
        con.commit()

        self.assertGreaterEqual(prune.prune_sessions(con, cutoff), 1)
        self.assertEqual(con.execute("SELECT count(*) FROM session_v2 WHERE id='ses_old'").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM session_v2 WHERE id='ses_fresh'").fetchone()[0], 1)

    def test_missing_session_v2_fails_loudly(self):
        """An unexpected schema must abort, not silently log success."""
        tmp = tempfile.TemporaryDirectory(prefix="prune-v1-")
        self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(os.path.join(tmp.name, "opencode.db"))
        self.addCleanup(con.close)
        for statement in LEGACY_SCHEMA:
            con.execute(statement)
        con.commit()
        with self.assertRaises(sqlite3.Error):
            prune.prune_sessions(con, int(time.time() * 1000))


if __name__ == "__main__":
    unittest.main()
