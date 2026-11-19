#!/usr/bin/env python3
"""pg_to_mariadb_copy — data-only PostgreSQL -> MariaDB copy for a tenant whose
schema was built by the application's own migrations.

WHY THIS EXISTS
    WP-10 moves Firefly III off PostgreSQL onto the private MariaDB tier. The
    schema is NOT translated here: Firefly's own migrations build the MariaDB
    schema (start the same image against an empty database and its entrypoint
    runs `firefly-iii:upgrade-database`). This tool copies DATA ONLY, table by
    table, and then proves the copy row by row.

WHY NOT `pg_dump | mysql`
    That is a cross-ENGINE text pipeline with silent-corruption failure modes:
    booleans dump as `t`/`f`, bytea as `\\x...`, timestamps may carry an offset,
    MySQL treats backslash as an escape character inside string literals,
    `bigserial` does not exist, and `NULL`/empty-string are indistinguishable in
    CSV. Each row is therefore read as JSON (which preserves null vs '', decimal
    scale and timestamps), converted column by column against the TARGET's own
    information_schema, and written as an explicit INSERT.

WHAT IT DOES
    1. reads the target schema (table/column/type/nullability/auto_increment)
       and refuses when a table or column differs from the source;
    2. computes a parent-before-child order from PostgreSQL's foreign keys and
       loads in that order, with FOREIGN_KEY_CHECKS=0 for the session anyway
       (cycles and any order mistake then cannot abort the load halfway);
    3. converts booleans to 0/1, decimals through Decimal (never float), dates
       and timestamps verbatim, uuid -> char(36) text, strings with backslash
       escaping disabled (NO_BACKSLASH_ESCAPES) and single quotes doubled;
    4. after each table sets AUTO_INCREMENT to max(id)+1 (only for tables that
       actually carry an auto_increment column);
    5. `--verify` compares every table row by row against the source, plus the
       financial invariants (per-currency transaction sums and every account's
       balance, which is what Firefly's UI computes in
       app/Support/Steam.php::accountsBalancesOptimized).

USAGE
    python3 pg_to_mariadb_copy.py order
    python3 pg_to_mariadb_copy.py load   --target-container X --target-db firefly \
        --target-user firefly [--password-stdin] [--truncate] [--dry-run]
    python3 pg_to_mariadb_copy.py verify --target-container X --target-db firefly \
        --target-user firefly [--password-stdin]

    Source defaults: --source-container shared.db --source-db firefly
    --source-user firefly (the container's local socket trusts that role).

    The password is read from the first line of stdin (--password-stdin) and is
    never placed on a command line or in an environment visible to the host:
    inside the target container it reaches the client through a shell `read`,
    the same discipline as `dbops`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from decimal import Decimal

# ---------------------------------------------------------------------------
# docker/psql/mariadb plumbing
# ---------------------------------------------------------------------------


class CopyError(RuntimeError):
    pass


def docker_exec(container: str, argv: list[str], stdin_data: bytes | None = None) -> bytes:
    cmd = ["docker", "exec", "-i", container, *argv]
    proc = subprocess.run(cmd, input=stdin_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise CopyError(
            f"docker exec {container} {' '.join(argv[:3])} failed rc={proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()[:2000]}"
        )
    return proc.stdout


def psql_json(container: str, user: str, db: str, sql: str) -> list[dict]:
    """Run SQL, parse one JSON object per line (row_to_json)."""
    out = docker_exec(container, ["psql", "-U", user, "-d", db, "-At", "-c", sql])
    rows = []
    for line in out.decode("utf-8").splitlines():
        if not line:
            continue
        rows.append(json.loads(line, parse_float=Decimal))
    return rows


def mariadb_json(container: str, user: str, password: str, db: str, sql: str) -> list[dict]:
    """Run SQL inside the target container; JSON_OBJECT rows, password on stdin.

    The password is the first line of stdin; the shell `read`s it into a
    variable, exports MYSQL_PWD for the client only, and the client reads the
    SQL from the remaining stdin. Nothing secret is in docker's argv.
    """
    payload = password.encode() + b"\n" + sql.encode()
    out = docker_exec(
        container,
        [
            "sh",
            "-c",
            'read -r P; MYSQL_PWD="$P" exec mariadb --skip-ssl --batch --raw --skip-column-names '
            f'--default-character-set=utf8mb4 -u{user} {db}',
        ],
        stdin_data=payload,
    )
    rows = []
    for line in out.decode("utf-8").splitlines():
        if not line:
            continue
        rows.append(json.loads(line, parse_float=Decimal))
    return rows


def mariadb_script(container: str, user: str, password: str, db: str, sql: str) -> None:
    """Run a multi-statement script (no result expected) with the password on stdin."""
    payload = password.encode() + b"\n" + sql.encode()
    docker_exec(
        container,
        [
            "sh",
            "-c",
            'read -r P; MYSQL_PWD="$P" exec mariadb --skip-ssl --batch '
            f'--default-character-set=utf8mb4 -u{user} {db}',
        ],
        stdin_data=payload,
    )


# ---------------------------------------------------------------------------
# schema + ordering
# ---------------------------------------------------------------------------


def target_schema(container: str, user: str, password: str, db: str) -> dict[str, list[dict]]:
    rows = mariadb_json(
        container,
        user,
        password,
        db,
        """
        SELECT JSON_OBJECT(
          'table', table_name, 'column', column_name, 'data_type', data_type,
          'column_type', column_type, 'nullable', is_nullable,
          'extra', extra, 'char_len', coalesce(character_maximum_length, 0))
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
        ORDER BY table_name, ordinal_position
        """,
    )
    schema: dict[str, list[dict]] = {}
    for r in rows:
        schema.setdefault(r["table"], []).append(r)
    return schema


def source_columns(container: str, user: str, db: str) -> dict[str, list[str]]:
    rows = psql_json(
        container,
        user,
        db,
        """
        SELECT row_to_json(x) FROM (
          SELECT table_name, column_name
          FROM information_schema.columns
          WHERE table_schema = 'public'
          ORDER BY table_name, ordinal_position) x
        """,
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["table_name"], []).append(r["column_name"])
    return out


def fk_edges(container: str, user: str, db: str) -> list[tuple[str, str]]:
    rows = psql_json(
        container,
        user,
        db,
        """
        SELECT row_to_json(x) FROM (
          SELECT tc.table_name AS child, ccu.table_name AS parent
          FROM information_schema.table_constraints tc
          JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
           AND ccu.constraint_schema = tc.constraint_schema
          WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public') x
        """,
    )
    return sorted({(r["child"], r["parent"]) for r in rows})


def table_order(tables: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Parents first (Kahn). A cycle is reported and the rest appended sorted."""
    deps = {t: set() for t in tables}
    for child, parent in edges:
        if child in deps and parent in deps and child != parent:
            deps[child].add(parent)
    order: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(t for t, d in remaining.items() if not (d - set(order)))
        if not ready:
            cycle = sorted(remaining)
            print(f"WARNING: foreign-key cycle among {cycle}; appending alphabetically", file=sys.stderr)
            order.extend(cycle)
            break
        for t in ready:
            order.append(t)
            del remaining[t]
    return order


def table_counts(container: str, user: str, db: str, tables: list[str], kind: str, password: str = "") -> dict[str, int]:
    out = {}
    if kind == "pg":
        rows = psql_json(
            container,
            user,
            db,
            " UNION ALL ".join(
                f"SELECT row_to_json(x) FROM (SELECT '{t}' AS t, count(*) AS n FROM \"{t}\") x"
                for t in tables
            ),
        )
    else:
        rows = mariadb_json(
            container,
            user,
            password,
            db,
            " UNION ALL ".join(
                f"SELECT JSON_OBJECT('t', '{t}', 'n', (SELECT count(*) FROM `{t}`))" for t in tables
            ),
        )
    for r in rows:
        out[r["t"]] = int(r["n"])
    return out


# ---------------------------------------------------------------------------
# value conversion
# ---------------------------------------------------------------------------


def sql_literal(value, col: dict) -> str:
    if value is None:
        return "NULL"
    dtype = col["data_type"]
    # PostgreSQL JSON: boolean -> bool, integer -> int, numeric -> Decimal,
    # timestamp/date/uuid/text -> str.
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        # exact scale as the source holds it; the target decimal(32,12) accepts it
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # NO_BACKSLASH_ESCAPES is set for the session, so only ' needs doubling.
        return "'" + value.replace("'", "''") + "'"
    raise CopyError(f"column {col['table']}.{col['column']}: unsupported JSON value {value!r} ({dtype})")


def canonical(value, col: dict):
    """Engine-independent form used by --verify."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # PostgreSQL's row_to_json renders timestamps as ISO-8601 with a `T`;
        # MariaDB's JSON_OBJECT renders them with a space. Same instant, so
        # compare the engine-neutral SQL form.
        if col["data_type"] in ("timestamp", "datetime"):
            return value.replace("T", " ", 1)
        # CHAR(n) is blank-padded by both engines but PG's row_to_json and
        # MariaDB's retrieval disagree on trailing spaces; the value itself is
        # fixed-width by definition, so compare it unpadded.
        if col["data_type"] == "char":
            return value.rstrip(" ")
        return value
    return str(value)


def quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load(args, password: str) -> None:
    p_schema = target_schema(args.target_container, args.target_user, password, args.target_db)
    p_cols = source_columns(args.source_container, args.source_user, args.source_db)
    edges = fk_edges(args.source_container, args.source_user, args.source_db)

    src_tables = set(p_cols)
    dst_tables = set(p_schema)
    if src_tables != dst_tables:
        raise CopyError(
            "table sets differ before any data was written: "
            f"only source={sorted(src_tables - dst_tables)} only target={sorted(dst_tables - src_tables)}"
        )
    for t in sorted(src_tables):
        s = p_cols[t]
        d = [c["column"] for c in p_schema[t]]
        # Same COLUMN SET is what matters: every value is addressed by name, so
        # a migration that reordered a table on one engine is harmless. Measured:
        # account_balances differs only in order (date_tz moved ahead of
        # transaction_journal_id/balance on MariaDB).
        if set(s) != set(d):
            raise CopyError(f"table {t}: column sets differ: source={s} target={d}")
        if s != d:
            print(f"  note: {t} column order differs (same set); values are matched by name")

    order = table_order(sorted(src_tables), edges)
    print("load order (parents first):")
    for i, t in enumerate(order, 1):
        print(f"  {i:2d}. {t}")

    if args.dry_run:
        print("dry run: schema and order validated, nothing written")
        return

    if args.truncate:
        stmts = ["SET FOREIGN_KEY_CHECKS=0;"]
        for t in reversed(order):
            stmts.append(f"TRUNCATE TABLE {quote_ident(t)};")
        stmts.append("SET FOREIGN_KEY_CHECKS=1;")
        mariadb_script(args.target_container, args.target_user, password, args.target_db, "\n".join(stmts))
        print(f"truncated {len(order)} tables")

    stats = {}
    for t in order:
        cols = p_schema[t]
        col_names = ", ".join(quote_ident(c["column"]) for c in cols)
        # One JSON object per row; row_to_json preserves null vs empty string and
        # Decimal scale, which CSV cannot.
        rows = psql_json(
            args.source_container,
            args.source_user,
            args.source_db,
            f'SELECT row_to_json(t)::text FROM "{t}" t',
        )
        values = []
        max_auto = None
        auto_col = next((c["column"] for c in cols if "auto_increment" in (c["extra"] or "")), None)
        for row in rows:
            vals = [sql_literal(row.get(c["column"]), c) for c in cols]
            values.append("(" + ", ".join(vals) + ")")
            if auto_col is not None and row.get(auto_col) is not None:
                n = int(row[auto_col])
                max_auto = n if max_auto is None else max(max_auto, n)
        writes = 0
        for start in range(0, len(values), args.batch_rows):
            batch = values[start : start + args.batch_rows]
            sql = (
                "SET SESSION sql_mode = CONCAT(@@sql_mode, ',NO_BACKSLASH_ESCAPES');\n"
                "SET SESSION time_zone = '+00:00';\n"
                "SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                "SET FOREIGN_KEY_CHECKS=0;\n"
                "SET UNIQUE_CHECKS=0;\n"
                f"INSERT INTO {quote_ident(t)} ({col_names}) VALUES\n" + ",\n".join(batch) + ";\n"
                "SET FOREIGN_KEY_CHECKS=1;\n"
                "SET UNIQUE_CHECKS=1;\n"
            )
            mariadb_script(args.target_container, args.target_user, password, args.target_db, sql)
            writes += len(batch)
        if auto_col is not None and max_auto is not None:
            mariadb_script(
                args.target_container,
                args.target_user,
                password,
                args.target_db,
                f"ALTER TABLE {quote_ident(t)} AUTO_INCREMENT = {max_auto + 1};\n",
            )
        stats[t] = {"rows": writes, "auto_increment": (max_auto + 1) if max_auto is not None else None}
        print(f"  {t}: {writes} rows" + (f", AUTO_INCREMENT={max_auto + 1}" if max_auto is not None else ""))

    print(f"loaded {sum(v['rows'] for v in stats.values())} rows into {len(stats)} tables")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def fetch_rows(container, user, db, table, columns, password="", kind="pg") -> dict:
    """Return {(pk...) -> canonical row tuple} for one table, keyed by all columns
    if there is no single id (the multiset is still compared exactly)."""
    if kind == "pg":
        sql = f'SELECT row_to_json(t)::text FROM "{table}" t'
        raw = psql_json(container, user, db, sql)
    else:
        obj = ", ".join(f"'{c['column']}', {quote_ident(c['column'])}" for c in columns)
        sql = f"SELECT JSON_OBJECT({obj}) FROM {quote_ident(table)}"
        raw = mariadb_json(container, user, password, db, sql)
    out = {}
    for r in raw:
        canon = tuple(canonical(r.get(c["column"]), c) for c in columns)
        out[canon] = out.get(canon, 0) + 1
    return Counter(out)


def verify(args, password: str) -> int:
    p_schema = target_schema(args.target_container, args.target_user, password, args.target_db)
    p_cols = source_columns(args.source_container, args.source_user, args.source_db)
    order = table_order(sorted(p_cols), fk_edges(args.source_container, args.source_user, args.source_db))

    failures = []
    print(f"{'table':32s} {'source':>8s} {'target':>8s}  result")
    for t in order:
        cols = p_schema[t]
        src = fetch_rows(args.source_container, args.source_user, args.source_db, t, cols, kind="pg")
        dst = fetch_rows(args.target_container, args.target_user, args.target_db, t, cols, password, kind="my")
        src_n = sum(src.values())
        dst_n = sum(dst.values())
        if src == dst:
            result = "identical"
        else:
            missing = sum((src - dst).values())
            extra = sum((dst - src).values())
            result = f"DIFF missing={int(missing)} extra={int(extra)}"
            failures.append((t, src_n, dst_n, int(missing), int(extra)))
        print(f"{t:32s} {src_n:8d} {dst_n:8d}  {result}")

    print("\nunique indexes under the TARGET collation:")
    # The load runs with UNIQUE_CHECKS=0, and InnoDB does not re-validate rows
    # that were written while it was off. A cross-engine move can therefore
    # leave a case-only duplicate that PostgreSQL allowed under a
    # case-sensitive collation. Check every non-primary unique index here, on
    # the data that is actually in the target.
    uniques = mariadb_json(
        args.target_container,
        args.target_user,
        password,
        args.target_db,
        """SELECT JSON_OBJECT('t', table_name, 'i', index_name,
                              'c', group_concat(column_name ORDER BY seq_in_index)) AS j
           FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND non_unique = 0 AND index_name <> 'PRIMARY'
           GROUP BY table_name, index_name ORDER BY table_name, index_name""",
    )
    unique_bad = []
    for u in uniques:
        cols = [c for c in (u["c"] or "").split(",") if c]
        group = ", ".join(quote_ident(c) for c in cols)
        sql = (
            "SELECT JSON_OBJECT('n', (SELECT COUNT(*) FROM ("
            f"SELECT 1 FROM {quote_ident(u['t'])} GROUP BY {group} HAVING COUNT(*) > 1) d)) AS j"
        )
        n = int(mariadb_json(args.target_container, args.target_user, password, args.target_db, sql)[0]["n"])
        if n:
            unique_bad.append((u["t"], u["i"], cols, n))
    if unique_bad:
        print(f"  DUPLICATE KEYS: {len(unique_bad)} unique index(es) violated")
        for t, i, cols, n in unique_bad[:10]:
            print(f"    {t}.{i} ({', '.join(cols)}): {n} duplicate group(s)")
        failures.append(("unique-indexes", 0, 0, 0, 0))
    else:
        print(f"  {len(uniques)} non-primary unique indexes, 0 duplicate groups")

    print("\nfinancial invariants (the same expressions on both engines):")

    def money(v):
        return Decimal(v) if v is not None else Decimal(0)

    # Per-currency transaction sums. Firefly's UI balance is the per-account
    # equivalent; this is the ledger-level check that the amounts survived.
    pg_cur = psql_json(
        args.source_container,
        args.source_user,
        args.source_db,
        """SELECT row_to_json(x) FROM (
             SELECT tc.code AS code, count(*) AS n, sum(t.amount) AS total
             FROM transactions t JOIN transaction_currencies tc ON tc.id = t.transaction_currency_id
             GROUP BY tc.code ORDER BY tc.code) x""",
    )
    my_cur = mariadb_json(
        args.target_container,
        args.target_user,
        password,
        args.target_db,
        """SELECT JSON_OBJECT('code', code, 'n', n, 'total', total) FROM (
             SELECT tc.code AS code, count(*) AS n, sum(t.amount) AS total
             FROM transactions t JOIN transaction_currencies tc ON tc.id = t.transaction_currency_id
             GROUP BY tc.code) x ORDER BY code""",
    )
    pg_cur = [(r["code"], int(r["n"]), money(r["total"])) for r in pg_cur]
    my_cur = [(r["code"], int(r["n"]), money(r["total"])) for r in my_cur]
    if pg_cur == my_cur:
        print(f"  per-currency sums identical: {len(pg_cur)} currencies, "
              + ", ".join(f"{c}:{n} rows/{v}" for c, n, v in pg_cur[:6]))
    else:
        print(f"  PER-CURRENCY SUMS DIFFER\n    source={pg_cur}\n    target={my_cur}")
        failures.append(("transactions-per-currency", 0, 0, 0, 0))

    # Per-account balances: accountsBalancesOptimized() sums transactions.amount
    # per (account, currency) and adds the account's virtual balance.
    balance_sql_pg = """SELECT row_to_json(x) FROM (
        SELECT a.id AS id, a.name AS name,
               coalesce(a.virtual_balance, 0) AS virtual_balance,
               coalesce(sum(t.amount), 0) AS tx_sum, count(t.id) AS tx_count
        FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id, a.name, a.virtual_balance ORDER BY a.id) x"""
    balance_sql_my = """SELECT JSON_OBJECT('id', id, 'name', name,
               'virtual_balance', virtual_balance, 'tx_sum', tx_sum, 'tx_count', tx_count) FROM (
        SELECT a.id AS id, a.name AS name,
               coalesce(a.virtual_balance, 0) AS virtual_balance,
               coalesce(sum(t.amount), 0) AS tx_sum, count(t.id) AS tx_count
        FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id, a.name, a.virtual_balance) x ORDER BY id"""
    pg_bal = psql_json(args.source_container, args.source_user, args.source_db, balance_sql_pg)
    my_bal = mariadb_json(args.target_container, args.target_user, password, args.target_db, balance_sql_my)
    pg_bal = [(int(r["id"]), r["name"], money(r["virtual_balance"]), money(r["tx_sum"]), int(r["tx_count"])) for r in pg_bal]
    my_bal = [(int(r["id"]), r["name"], money(r["virtual_balance"]), money(r["tx_sum"]), int(r["tx_count"])) for r in my_bal]
    if pg_bal == my_bal:
        total = sum(r[3] for r in pg_bal)
        print(f"  account balances identical: {len(pg_bal)} accounts, ledger total {total}")
    else:
        diffs = [(a, b) for a, b in zip(pg_bal, my_bal) if a != b]
        print(f"  ACCOUNT BALANCES DIFFER ({len(diffs)} of {len(pg_bal)})")
        for a, b in diffs[:10]:
            print(f"    source={a}\n    target={b}")
        failures.append(("account-balances", 0, 0, 0, 0))

    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        return 1
    print("\nOK: every table row-identical; financial invariants identical")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["order", "load", "verify"])
    ap.add_argument("--source-container", default="shared.db")
    ap.add_argument("--source-db", default="firefly")
    ap.add_argument("--source-user", default="firefly")
    ap.add_argument("--target-container", default="")
    ap.add_argument("--target-db", default="firefly")
    ap.add_argument("--target-user", default="firefly")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the target account's password from the first stdin line")
    ap.add_argument("--password-file", default="",
                    help="read the target account's password from the first line of this file")
    ap.add_argument("--truncate", action="store_true", help="empty the target tables first")
    ap.add_argument("--dry-run", action="store_true", help="validate schema + order, write nothing")
    ap.add_argument("--batch-rows", type=int, default=500)
    args = ap.parse_args()

    if args.command in ("load", "verify") and not args.target_container:
        ap.error("--target-container is required for load/verify")

    password = ""
    if args.password_file:
        with open(args.password_file, "r", encoding="utf-8") as fh:
            password = fh.readline().rstrip("\n")
    elif args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    if args.command in ("load", "verify") and not password:
        raise CopyError("the target password was empty (--password-file/--password-stdin)")

    try:
        if args.command == "order":
            p_cols = source_columns(args.source_container, args.source_user, args.source_db)
            for i, t in enumerate(table_order(sorted(p_cols), fk_edges(args.source_container, args.source_user, args.source_db)), 1):
                print(f"{i:2d}. {t}")
            return 0
        if args.command == "load":
            load(args, password)
            return 0
        return verify(args, password)
    except CopyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
