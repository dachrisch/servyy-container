# Moodle "Convert submission" failures — the image was running without Ghostscript

**Date:** 2026-11-21
**Service:** `moodle.moodle` (`https://offd.de`, servy.lehel.xyz)
**Reported as:** admin mail *"Die Task Convert submission ist mehrmals fehlgeschlagen und
erfordert Ihre Aufmerksamkeit."*

## Problem

The ad-hoc task `assignfeedback_editpdf\task\convert_submission` (the **Annotate PDF**
grading feedback method) failed on every attempt:

```
Adhoc task failed: assignfeedback_editpdf\task\convert_submission,
Der Pfad zu Ghostscript ist nicht richtig konfiguriert:
Der Ghostscript-Pfad zeigt auf eine nicht vorhandene Datei. (doesnotexist)
```

`mdl_config.pathtogs` is `/usr/bin/gs` (inherited with the imported shared-hosting DB), but
the container had **no Ghostscript**: `apk info -e ghostscript` failed, `/usr/share/ghostscript`
did not exist. The DB therefore also carried `pathtounoconv=/usr/bin/unoconv`, likewise absent.

Impact, measured in `mdl_task_log`:

- **0 successful** `convert_submission` runs ever on this host, **20 failed**.
- First failure 2026-11-19 20:13; five tasks stuck, `attemptsavailable=0`, `faildelay` at the
  86 400 s cap — i.e. parked, never retried: submissions 1388 + 1410 (Kay Klippel), 1423
  (Sven Krüger), 1441 (Florian Kochendörfer) in *Erste Hilfe Nachweis*, and 879 (Maurice
  Plein) in *Anti-Doping Zertifikat*.
- 55 assignments have the editpdf feedback method enabled, so every PDF/JPG submission was
  affected; grading itself worked, only the annotation page did not.

## Why it happened

`erseco/alpine-moodle` shipped no Ghostscript until
[erseco/alpine-moodle#197](https://github.com/erseco/alpine-moodle/pull/197) (2026-11-19,
"Add Ghostscript for Moodle PDF annotation"), which also sets `pathtogs` at boot when it is
empty. The local image was the **2026-11-12 build** of `4.5.16`
(`sha256:bdce0009…`), i.e. older than that PR. The deploy's `pull: omit` kept compose's
`missing` policy, so a present tag was never refreshed — even though upstream had
**re-published `4.5.16` on 2026-11-20** (`sha256:85cd21d2…`, contains `/usr/bin/gs` 10.08.0).

Note `unoconv` is *not* worth installing: the only non-PDF/JPG submission rows in the DB
belong to deleted assignments.

## What was done

1. Hotfix in the running container (`docker exec -u root … apk add --no-cache ghostscript`),
   then requeued the five parked tasks (`faildelay=0`, `timestarted=NULL`,
   `attemptsavailable=3`, `nextruntime=now`). All five completed at 09:29:37–09:29:52 and each
   grade now has its `pages` + `combined` PDF in `mdl_files` (verified per submission).
   Moodle's own `pdf::test_gs_path(true)` returns `status=ok`.
2. Durable fix: the moodle deploy now sets **`compose_pull: always`**
   ([`ansible/plays/user.yml`](../ansible/plays/user.yml)) — upstream rebuilds published tags
   in place, so `missing` silently keeps an outdated image forever. A redeploy therefore
   replaces the hotfixed container with the Ghostscript-carrying image and the `apk add`
   drift disappears.
3. Documented the dependency and the verification command in
   [`moodle/AGENTS.md`](../moodle/AGENTS.md).

## Verification

```bash
ssh lehel.xyz "docker exec moodle.moodle gs --version"            # 10.08.0
ssh lehel.xyz "docker exec -u 65534 moodle.moodle php /var/www/html/admin/cli/cfg.php --name=pathtogs"
psql-free check: the five submissions must have pages+combined files, and
mdl_task_adhoc must be empty while mdl_task_log shows result=0 for the class.
```

## Deployment result (2026-11-21, 10:19 CET)

- Host checkout fast-forwarded `f9a1084` → `e7d70f2` (PR #333); git-crypt healthy.
- Deployed with the `docker_service` role's exact module
  (`community.docker.docker_compose_v2`, `pull: always`) against
  `/home/cda/servyy-container/moodle`: `Pulling → Pulled → Recreate → Started`.
  New container runs **`sha256:85cd21d2…`** (the 2026-11-20 rebuild), restarts 0,
  health `healthy`, `https://offd.de/` 200.
- `apk info -e ghostscript` inside the new container lists the package (it comes from
  the image now — no `apk add` drift), `gs --version` = 10.08.0,
  `pdf::test_gs_path(true)` = `status=ok`.
- `convert_submission`: **0 failures since 09:29**, ad-hoc queue empty, and a fresh
  end-to-end conversion (submission 1388, queued 10:20) finished `result=0` at 10:21.
- Note for the next operator: the full `servyy.yml` play cannot be run from the
  opencode controller — the machine-local password seeds (`ansible/plays/vars/.moodle_*`,
  `.restic_password_*`, …) are absent there and `secret_seed_guard` correctly refuses to
  regenerate them (that would have written fresh credentials into `app.env`). Run the
  whole playbook from a checkout that holds the seeds; otherwise deploy the single role
  with its compose module as above. The seeds are on no host checkout (`find` over servy
  and codey found none), which is worth fixing — a controller without them cannot do a
  full deploy.

Lesson: a mutable upstream tag is not a version. Any service that pins a tag whose upstream
CI rebuilds in place needs `compose_pull: always` (precedent: `waggle`'s `latest`), otherwise
"we deployed the tag" means "we kept whatever was pulled first".
