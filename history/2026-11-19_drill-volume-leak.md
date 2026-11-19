# The drills filled the Docker data volume — 2026-11-19

**Found by:** the disk alerts, right after R11's drills ran for the first time.
**Impact:** none on service; 10.3 GB of the 49 GB Docker data volume (97% full, 2 GB
free) was recoverable garbage, and the next image pull or drill could have failed.
**Cause:** our own drill script. **Fixed in** `db-tier/…` → merged on master with
`roles/restore_drill/templates/restore_drill.sh.j2`.

## What was measured

| | |
|---|---|
| `Low Disk` / `Root Disk Almost Full` | firing, `avail/size = 3.9%` on `mountpoint="/"`, `device=/dev/sda1` |
| `df -h /` on the host | **64% used, 27.8 GB free** — the host disk was never the problem |
| `df -h /mnt/servy-docker-data` | **97%, 2.0 GB free** — this is what the alerts were actually describing |
| `docker system df` | volumes: 64 total, 19 active, 10.91 GB reclaimable |
| dangling volumes | **45**, 10.67 GB, timestamps `09:22`–`09:48` = the drill window |
| at 02:02 that morning | 21 volumes, 0.6 GB reclaimable |

So: ~43 anonymous volumes were created in one night of drilling, and each held a
whole restored datadir (moodle 2.1 GB, photoprism ~1 GB, …).

## The mechanism

`mariadb`, `mongo` and `postgres` images all declare `VOLUME` (`/var/lib/mysql`,
`/data`, `/var/lib/postgresql/data`), so **every** scratch container was born with an
anonymous volume holding the whole restored copy. `cleanup_scratch()` removed the
container with `docker rm -f` — **without `-v`** — which detaches the volume instead of
deleting it. The drill reported `ok`, the evidence table said "scratch target →
removed", and the disk filled.

Proven causally on the host, not argued:

```
docker run -d --name drill-guardtest --entrypoint sleep mariadb:13.0 60
docker rm -f drill-guardtest                    # no -v
dangling volumes: 2 -> 3
```

And after the fix, the same drill (photoprism, 109.7 s): dangling count stays at 2,
`/mnt/servy-docker-data` stays at 77%.

## The fix, and the guard that makes a regression loud

1. `docker rm -fv` — the `-v` is not optional, and the comment in the template says
   why (it names this incident).
2. Every drill now records `docker volume ls -qf dangling=true | wc -l` **before** its
   scratch target exists and compares after cleanup. Growth ⇒ the drill **fails** with
   `left N dangling volume(s) behind (scratch target not fully removed)`. A restore that
   works but eats the disk is not a passing drill; this is the "silent no-op" pattern
   again — the drill was green while the host was 97% full.

Reclaimed immediately: `docker volume prune -f` → **10.29 GB**, docker data volume
97% → 77%.

## Two things a reader should take away

- **`docker volume prune` does not touch named volumes** (`bnb-office_db_data`,
  `dontforget_mongo9_data` survive both it and the nightly `docker system prune
  --volumes`). The anonymous-volume leak above was invisible to that nightly too — it
  ran 18 h before, and 18 h before the next one is long enough to fill the disk.
- **Node-exporter is reporting the container overlay, not the host disk.** It says
  `/dev/sda1` mounted `/` with 52.5 GB size and 2.07 GB free; the host's `/dev/sda1` is
  80.3 GB with 27.8 GB free, and 52.5 GB/2.07 GB is exactly
  `/mnt/servy-docker-data` (49 GiB, 96%). So the three disk rules were *right about
  capacity* and *wrong about the device*: they monitor the Docker data volume while
  calling it the root disk. Nothing was mis-decided tonight because `df` was checked by
  hand; the fix (host root exported with `--path.rootfs=/host` and labelled honestly) is
  recorded as follow-up work, not done inside the database programme.
