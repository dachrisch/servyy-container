#!/usr/bin/env bash
# Verify an OFFD export BEFORE it is allowed near the live instance.
#
# Run on servy (needs docker to read the live database); it only reads. Exits
# non-zero on any hard failure, so it can gate the import:
#
#   moodle/scripts/verify-offd-export.sh moodledata.tar.gz dump.sql.gz && \
#     moodle/scripts/import-offd-release.sh moodledata.tar.gz dump.sql.gz
#
# The checks, in the order that matters:
#
#  1. both files are gzip containers that decompress end to end (`gzip -t`) —
#     a truncated upload is the most likely failure mode;
#  2. the tar is structurally sane: expected top level, permanent dataroot
#     directories, no symlinks/hardlinks/devices, no absolute or `..` paths, and
#     none of the transient directories (cache, sessions, temp, localcache, muc)
#     that must never be merged into a live dataroot;
#  3. **every `filedir` file hashes to its own filename**. That is the check that
#     caught the 2026-11-03 export: downloaded over FTP in ASCII mode, all 9 496
#     files were present *by name* while 9 247 were mangled. A complete-looking
#     file set proves nothing; content hashing does;
#  4. every `contenthash` the database references exists in the archive (missing
#     = broken pluginfile.php links). Files on disk without a database row are
#     reported as orphans, not failed — they are uploads made after the dump;
#  5. the SQL dump is a plain data dump (no CREATE DATABASE / USE) of a Moodle
#     schema (`mdl_config` present) with a plausible table count.
#
# Both streams are read once: ~1–2 min for 6 GB on local disk, longer from the
# Storage Box (CIFS). Do not skip this to save time on release day.

set -euo pipefail

ARCHIVE="${1:-}"
DUMP="${2:-}"

fail() { printf '\n\033[31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m ok \033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarn\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[[ -n "$ARCHIVE" && -n "$DUMP" ]] || fail "usage: $(basename "$0") <moodledata.tar.gz> <dump.sql.gz>"
[[ -f "$ARCHIVE" ]] || fail "no such archive: $ARCHIVE"
[[ -f "$DUMP" ]] || fail "no such dump: $DUMP"
command -v docker >/dev/null || fail "docker not found — run this on servy, it reads the live database"
docker inspect -f '{{.State.Health.Status}}' moodle.db >/dev/null 2>&1 \
  || fail "moodle.db is not running — the contenthash coverage check needs the live database"

printf 'archive : %s (%s bytes)\ndump    : %s (%s bytes)\n' \
  "$ARCHIVE" "$(stat -c%s "$ARCHIVE")" "$DUMP" "$(stat -c%s "$DUMP")"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

step "gzip integrity"
gzip -t "$ARCHIVE" || fail "archive fails gzip -t (truncated or corrupt upload)"
gzip -t "$DUMP" || fail "dump fails gzip -t (truncated or corrupt upload)"
ok "both streams decompress end to end"

step "live database content hashes"
sudo chmod 777 "$TMP"
docker exec -i moodle.db sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" --batch --skip-column-names moodle' \
  <<'SQL' | tr -d '\r' > "$TMP/db_hashes"
SELECT DISTINCT contenthash FROM mdl_files WHERE contenthash IS NOT NULL AND contenthash <> '';
SQL
DB_HASHES="$(wc -l < "$TMP/db_hashes")"
[[ "$DB_HASHES" -gt 1000 ]] || fail "only $DB_HASHES contenthash rows in the database — wrong database?"
ok "$DB_HASHES distinct contenthash values in mdl_files"

step "one full pass over the archive (structure + sha1 + coverage)"
sudo python3 - "$ARCHIVE" "$TMP/db_hashes" > "$TMP/report" <<'PY'
import hashlib, re, sys, tarfile

path, hashfile = sys.argv[1], sys.argv[2]
filedir_pat = re.compile(r"^(?:moodledata/)?filedir/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{40})$")
transient = {"cache", "localcache", "muc", "sessions", "temp", "trashdir"}

tops, dataroot_dirs, problems = set(), set(), []
files = dirs = 0
hash_ok = hash_bad = 0
bad_examples, on_disk = [], set()

with tarfile.open(path, "r|gz") as tf:
    for m in tf:
        name = m.name.lstrip("./")
        if not name:
            continue
        parts = name.split("/")
        tops.add(parts[0] if parts[0] != "moodledata" else "moodledata")
        rel = parts[1:] if parts[0] == "moodledata" else parts
        if name.startswith("/") or ".." in parts:
            problems.append(f"unsafe path: {m.name}")
        if m.issym() or m.islnk():
            problems.append(f"link: {m.name}")
        if not (m.isfile() or m.isdir()):
            problems.append(f"special file: {m.name}")
        if m.isdir():
            dirs += 1
            if rel:
                dataroot_dirs.add(rel[0])
            continue
        files += 1
        if rel and rel[0] in transient:
            problems.append(f"transient dir content: {m.name}")
        mm = filedir_pat.match(name)
        if not mm:
            continue
        h = hashlib.sha1()
        fh = tf.extractfile(m)
        while chunk := fh.read(1 << 20):
            h.update(chunk)
        digest = h.hexdigest()
        on_disk.add(mm.group(3))
        if digest == mm.group(3):
            hash_ok += 1
        else:
            hash_bad += 1
            if len(bad_examples) < 5:
                bad_examples.append(f"{name} -> sha1 {digest}")

with open(hashfile) as fh:
    in_db = {line.strip() for line in fh if line.strip()}
missing = sorted(in_db - on_disk)
orphans = sorted(on_disk - in_db)

emit = lambda k, v: print(f"{k}={v}")
emit("tops", "+".join(sorted(tops)))
emit("files", files)
emit("dirs", dirs)
emit("dataroot_dirs", "+".join(sorted(dataroot_dirs)))
emit("problems", len(problems))
for p in problems[:10]:
    emit("problem", p)
emit("filedir_ok", hash_ok)
emit("filedir_bad", hash_bad)
for b in bad_examples:
    emit("filedir_bad_example", b)
emit("db_contenthashes", len(in_db))
emit("db_hashes_present", len(in_db) - len(missing))
emit("missing_on_disk", len(missing))
for m in missing[:10]:
    emit("missing", m)
emit("orphans_not_in_db", len(orphans))
PY

cat "$TMP/report"
get() { sed -n "s/^$1=//p" "$TMP/report" | head -1; }

[[ "$(get problems)" == "0" ]] || fail "unsafe entries in the archive (see problem= lines above)"
ok "no symlinks/hardlinks/devices, no absolute or .. paths, no transient directories"

grep -q '\bfiledir\b' <<<"$(get dataroot_dirs)" \
  || fail "no filedir/ in the archive — this is not a moodledata export"
for d in lang secret models environment diag; do
  grep -q "\b$d\b" <<<"$(get dataroot_dirs)" || warn "dataroot directory '$d' missing from the archive"
done
[[ "$(get tops)" == "moodledata" ]] \
  || warn "top level is '$(get tops)', not a single 'moodledata/' — the import script handles both shapes"
ok "structure sane ($(get files) files, $(get dirs) dirs, top level: $(get tops))"

[[ "$(get filedir_ok)" -gt 0 ]] || fail "no filedir files found in the archive"
[[ "$(get filedir_bad)" == "0" ]] \
  || fail "$(get filedir_bad) filedir files do not hash to their own filename — the ASCII/FTP corruption signature, see history/2026-11-03_moodle-moodledata-ascii-mangled.md. Reject this export."
ok "$(get filedir_ok) filedir files hash to their own filename, 0 bad"

[[ "$(get missing_on_disk)" == "0" ]] \
  || fail "$(get missing_on_disk) database contenthash values are NOT in the archive — pluginfile.php links would 404. Do not import."
ok "all $(get db_contenthashes) database contenthash values are present"
if [[ "$(get orphans_not_in_db)" != "0" ]]; then
  warn "$(get orphans_not_in_db) files are on disk but not in the database (uploads newer than the dump) — harmless, they become orphans"
fi

step "SQL dump"
TABLES="$(gzip -dc "$DUMP" | grep -c '^CREATE TABLE' || true)"
[[ "${TABLES:-0}" -ge 400 ]] || fail "only $TABLES CREATE TABLE statements — not the OFFD dump (497 expected)"
gzip -dc "$DUMP" | grep -q 'mdl_config' || fail "no mdl_config table in the dump"
if gzip -dc "$DUMP" | grep -Eq '^(CREATE DATABASE|USE )'; then
  fail "dump contains CREATE DATABASE/USE — it would not import into the target database cleanly"
fi
ok "$TABLES tables, mdl_ schema, no CREATE DATABASE/USE"

printf '\n\033[32mPASS\033[0m %s is safe to import.\n' "$(basename "$ARCHIVE")"
printf 'Next: moodle/scripts/import-offd-release.sh %q %q\n' "$ARCHIVE" "$DUMP"
