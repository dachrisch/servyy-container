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


LEGACY_TABLE_NAMES = (
    "session",
    "message",
    "part",
    "todo",
    "session_share",
    "session_input",
    "session_context_epoch",
)


def create_schema(con, legacy=True, drop_legacy=()):
    """Create the V2 schema, plus all legacy tables unless legacy=False.

    `drop_legacy` removes individual legacy tables afterwards, modelling a
    partially migrated database (only some V1 tables survived).
    """
    for statement in V2_SCHEMA:
        con.execute(statement)
    if legacy:
        for statement in LEGACY_SCHEMA:
            con.execute(statement)
    for name in drop_legacy:
        con.execute("DROP TABLE %s" % name)


def seed_v2_session(con, session_id, created, updated=None):
    """Insert one V2 session with dependent rows in every V2 table."""
    updated = created if updated is None else updated
    con.execute(
        "INSERT INTO session_v2 (id, project_id, slug, directory, title, version, time_created, time_updated)"
        " VALUES (?, 'prj_test', ?, '/tmp/project', ?, '2.1.2', ?, ?)",
        (session_id, "slug-" + session_id, "title " + session_id, created, updated),
    )
    con.execute(
        "INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data)"
        " VALUES (?, ?, 'text', 1, ?, ?, '{}')",
        (session_id + "_msg", session_id, created, updated),
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
        (session_id, created, updated),
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


def seed_legacy_session(con, session_id, created, updated=None, tables=None):
    """Insert one V1 session row plus its legacy child rows.

    `tables` restricts which legacy tables are populated, for partially
    migrated schemas; the default populates all of them.
    """
    updated = created if updated is None else updated
    tables = set(LEGACY_TABLE_NAMES) if tables is None else set(tables)
    if "session" in tables:
        con.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES (?, 'prj_test', ?, '/tmp/project', ?, '1.19.3', ?, ?)",
            (session_id, "slug-" + session_id, "title " + session_id, created, updated),
        )
    if "message" in tables:
        con.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, '{}')",
            (session_id + "_legacy_msg", session_id, created, updated),
        )
    if "part" in tables and "message" in tables:
        con.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, '{}')",
            (session_id + "_legacy_part", session_id + "_legacy_msg", session_id, created, updated),
        )
    if "todo" in tables:
        con.execute(
            "INSERT INTO todo (session_id, content, status, priority, position, time_created, time_updated)"
            " VALUES (?, 'c', 'pending', 'high', 0, ?, ?)",
            (session_id, created, updated),
        )
    if "session_share" in tables:
        con.execute(
            "INSERT INTO session_share (session_id, id, secret, url, time_created, time_updated)"
            " VALUES (?, ?, 's', 'https://example.invalid', ?, ?)",
            (session_id, "share-" + session_id, created, updated),
        )
    if "session_input" in tables:
        con.execute(
            "INSERT INTO session_input (id, session_id, time_created, data) VALUES (?, ?, ?, '{}')",
            (session_id + "_input", session_id, created),
        )
    if "session_context_epoch" in tables:
        con.execute(
            "INSERT INTO session_context_epoch (session_id, epoch_start, time_created) VALUES (?, 0, ?)",
            (session_id, created),
        )


def seed_session(con, session_id, created, updated=None, legacy=True, legacy_tables=None):
    """Insert one session with dependent rows in every V2 (and legacy) table."""
    seed_v2_session(con, session_id, created, updated)
    if legacy:
        seed_legacy_session(con, session_id, created, updated, tables=legacy_tables)


def count_rows(con, table, column, value):
    return con.execute(
        "SELECT count(*) FROM %s WHERE %s = ?" % (table, column), (value,)
    ).fetchone()[0]


class PruneSessionsTest(unittest.TestCase):
    """The idle session must disappear from session_v2 and every dependent table."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prune-test-")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "opencode.db")
        self.con = sqlite3.connect(self.db_path)
        self.addCleanup(self.con.close)
        create_schema(self.con, legacy=True)
        self.now_ms = int(time.time() * 1000)
        self.cutoff = self.now_ms - 3600_000
        self.stale = self.cutoff - 30 * 86400_000
        self.old = "ses_old"
        self.fresh = "ses_fresh"
        # Created 30 days before the cutoff *and* last updated then: idle.
        seed_session(self.con, self.old, self.stale)
        # Brand new on both clocks.
        seed_session(self.con, self.fresh, self.now_ms)
        # Created long ago but used seconds ago: must survive.
        self.active = "ses_long_lived"
        seed_session(self.con, self.active, self.stale, self.now_ms)
        # Stale, but only ever existed in V2 - no legacy row at all.
        self.v2_only = "ses_v2_only"
        seed_session(self.con, self.v2_only, self.stale, legacy=False)
        self.con.commit()

    def test_old_session_is_removed_from_session_v2(self):
        deleted = prune.prune_sessions(self.con, self.cutoff)
        # Two stale sessions (one in both tables, one V2-only), each reported
        # once even though the migrated one appears in both tables.
        self.assertEqual(deleted, 2)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0],
            0,
            "old session still present in session_v2 (V1 table was pruned instead)",
        )
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.fresh,)).fetchone()[0], 1
        )

    def test_v2_only_stale_session_is_pruned(self):
        """Pins the selection to session_v2: a session with no legacy row."""
        prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.v2_only,)).fetchone()[0],
            0,
            "V2-only session survived: the pruner is still selecting from the legacy table",
        )
        for table, column in prune.V2_DEPENDENT_TABLES:
            with self.subTest(table=table):
                self.assertEqual(count_rows(self.con, table, column, self.v2_only), 0)

    def test_created_and_updated_long_ago_is_deleted(self):
        prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0], 0
        )

    def test_long_lived_but_recently_active_session_survives(self):
        """An old session that was used within the window must not be pruned."""
        prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.active,)).fetchone()[0],
            1,
            "long-lived but active session was pruned: selection ignores time_updated",
        )
        for table, column in prune.V2_DEPENDENT_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, column, self.active),
                    1,
                    "%s lost rows of the active session" % table,
                )
        for table, column in prune.LEGACY_DEPENDENT_TABLES:
            with self.subTest(table=table, legacy=True):
                self.assertEqual(count_rows(self.con, table, column, self.active), 1)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session WHERE id = ?", (self.active,)).fetchone()[0], 1
        )

    def test_newer_v2_row_protects_old_legacy_row(self):
        """The surviving filter: a stale legacy row whose V2 twin is live stays."""
        diverged = "ses_diverged"
        seed_legacy_session(self.con, diverged, self.stale)
        seed_v2_session(self.con, diverged, self.stale, self.now_ms)
        self.con.commit()

        prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (diverged,)).fetchone()[0], 1
        )
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session WHERE id = ?", (diverged,)).fetchone()[0],
            1,
            "legacy row of a live V2 session was deleted: surviving filter is gone",
        )
        self.assertEqual(count_rows(self.con, "message", "session_id", diverged), 1)
        self.assertEqual(count_rows(self.con, "todo", "session_id", diverged), 1)

    def test_old_dependents_are_removed(self):
        prune.prune_sessions(self.con, self.cutoff)
        for table, column in V2_DEPENDENTS.items():
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, column, self.old),
                    0,
                    "%s still holds rows for the pruned session" % table,
                )
        # Same check driven by the script's own table list, so a newly added
        # dependent table is exercised here instead of being silently untested.
        for table, column in prune.V2_DEPENDENT_TABLES:
            with self.subTest(table=table, source="script"):
                self.assertEqual(count_rows(self.con, table, column, self.old), 0)

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
        self.assertEqual(first, 2)
        snapshot = {
            table: self.con.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
            for table in list(V2_DEPENDENTS) + list(LEGACY_DEPENDENTS) + ["session_v2", "session"]
        }
        second = prune.prune_sessions(self.con, self.cutoff)
        self.assertEqual(second, 0)
        for table, before in snapshot.items():
            with self.subTest(table=table):
                self.assertEqual(self.con.execute("SELECT count(*) FROM %s" % table).fetchone()[0], before)

    def test_legacy_only_stale_session_is_cleaned_and_counted(self):
        """V1 rows the migration never carried over are still dead weight."""
        old_only = "ses_legacy_only"
        seed_legacy_session(self.con, old_only, self.stale)
        self.con.commit()

        # old + v2_only + this legacy-only one.
        self.assertEqual(prune.prune_sessions(self.con, self.cutoff), 3)
        self.assertEqual(self.con.execute("SELECT count(*) FROM session WHERE id = ?", (old_only,)).fetchone()[0], 0)
        self.assertEqual(count_rows(self.con, "message", "session_id", old_only), 0)
        self.assertEqual(count_rows(self.con, "todo", "session_id", old_only), 0)

    def test_legacy_children_of_v2_only_session_are_cleaned(self):
        """A partially migrated database can hold V1 child rows for a V2-only id."""
        session_id = self.v2_only
        self.con.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, '{}')",
            (session_id + "_orphan_msg", session_id, self.stale, self.stale),
        )
        self.con.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, '{}')",
            (session_id + "_orphan_part", session_id + "_orphan_msg", session_id, self.stale, self.stale),
        )
        self.con.execute(
            "INSERT INTO todo (session_id, content, status, priority, position, time_created, time_updated)"
            " VALUES (?, 'c', 'pending', 'high', 0, ?, ?)",
            (session_id, self.stale, self.stale),
        )
        self.con.commit()

        prune.prune_sessions(self.con, self.cutoff)
        for table in ("part", "message", "todo"):
            with self.subTest(table=table):
                self.assertEqual(
                    count_rows(self.con, table, "session_id", self.v2_only),
                    0,
                    "orphan legacy rows of a pruned V2-only session survived",
                )

    def test_partially_migrated_schema_runs_cleanly(self):
        """session+message+part present, todo/session_share/input/epoch absent."""
        tmp = tempfile.TemporaryDirectory(prefix="prune-partial-")
        self.addCleanup(tmp.cleanup)
        con = sqlite3.connect(os.path.join(tmp.name, "opencode.db"))
        self.addCleanup(con.close)
        kept = ("session", "message", "part")
        create_schema(
            con,
            legacy=True,
            drop_legacy=[name for name in LEGACY_TABLE_NAMES if name not in kept],
        )
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - 3600_000
        stale = cutoff - 30 * 86400_000
        seed_session(con, "ses_old", stale, legacy_tables=kept)
        seed_session(con, "ses_fresh", now_ms, legacy_tables=kept)
        con.commit()

        self.assertEqual(prune.prune_sessions(con, cutoff), 1)
        self.assertEqual(con.execute("SELECT count(*) FROM session_v2 WHERE id='ses_old'").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM session WHERE id='ses_old'").fetchone()[0], 0)
        self.assertEqual(count_rows(con, "part", "session_id", "ses_old"), 0)
        self.assertEqual(con.execute("SELECT count(*) FROM session_v2 WHERE id='ses_fresh'").fetchone()[0], 1)
        self.assertEqual(count_rows(con, "part", "session_id", "ses_fresh"), 1)

    def _spy_on_vacuum(self):
        """Record vacuum() calls instead of running the real VACUUM."""
        calls = []
        original = prune.vacuum
        prune.vacuum = lambda con: calls.append(con)
        self.addCleanup(setattr, prune, "vacuum", original)
        return calls

    def _use_main(self, retention_hours):
        prune.DB_PATH = self.db_path
        prune.RETENTION_HOURS = retention_hours
        self.addCleanup(setattr, prune, "DB_PATH", os.environ["OPENCODE_DB"])
        self.addCleanup(setattr, prune, "RETENTION_HOURS", 24.0)
        self.con.commit()

    def test_main_prunes_live_sessions_and_vacuums(self):
        calls = self._spy_on_vacuum()
        self._use_main(1.0)
        self.assertEqual(prune.main(), 0)
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0], 0
        )
        # Rows were deleted, so vacuum is required and the fresh and active
        # sessions must still be there afterwards.
        self.assertEqual(len(calls), 1, "vacuum was not attempted after deleting rows")
        for session_id in (self.fresh, self.active):
            with self.subTest(session=session_id):
                self.assertEqual(
                    self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (session_id,)).fetchone()[0], 1
                )

    def test_main_skips_vacuum_when_nothing_is_deleted(self):
        calls = self._spy_on_vacuum()
        self._use_main(100000.0)
        self.assertEqual(prune.main(), 0)
        self.assertEqual(calls, [], "vacuum must not run when no rows were deleted")
        self.assertEqual(
            self.con.execute("SELECT count(*) FROM session_v2 WHERE id = ?", (self.old,)).fetchone()[0], 1
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

        self.assertEqual(prune.prune_sessions(con, cutoff), 1)
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
