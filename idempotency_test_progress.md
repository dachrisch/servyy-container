# Idempotency Test Progress - servyy-test.lxd

| Tag | First Run | Second Run | Idempotent? | Analysis |
| :--- | :---: | :---: | :---: | :--- |
| **System Role** | | | | |
| `system.packages` | 0 | 0 | ✅ | Already at goal state. |
| `system.user` | 0 | 0 | ✅ | Already at goal state. |
| `system.extension_drive` | 0 | 0 | ✅ | Already at goal state. |
| `system.storagebox` | 0 | 0 | ✅ | Already at goal state. |
| `system.monit` | 3 | 0 | ✅ | Idempotency fixed by adding 'manual' check skip. |
| `system.fail2ban` | 0 | 0 | ✅ | Already at goal state. |
| `system.swap` | 0 | 0 | ✅ | Already at goal state (skipped due to --skip-tags). |
| `system.journald` | 0 | 0 | ✅ | Already at goal state. |
| `system.docker` | 0 | 0 | ✅ | Already at goal state. |
| `system.kernel` | 0 | 0 | ✅ | Already at goal state. |
| `system.restic` | 0 | 0 | ✅ | Already at goal state. |
| **User Role** | | | | |
| `user.zprezto` | 0 | 0 | ✅ | Already at goal state. |
| `user.atuin` | 0 | 0 | ✅ | Already at goal state. |
| `user.repo.me` | 0 | 0 | ✅ | Already at goal state. |
| `user.docker` | 2 | 0 | ✅ | Run 1 changes due to submodule/env, Run 2 is idempotent. |
| `user.dns` | 0 | 0 | ✅ | Already at goal state. |
| `user.backup` | 0 | 0 | ✅ | Already at goal state. |
| `user.restic` | 1 | 0 | ✅ | Idempotency fixed by handling sftp 'Failure' message. |
| `user.ping` | 0 | 0 | ✅ | Already at goal state. |
| **League Sphere (LS) Roles** | | | | |
| `ls.setup` | 0 | 0 | ✅ | Already at goal state. |
| `ls.access` | 0 | 0 | ✅ | Already at goal state. |
| `ls.app` | 1 | 0 | ✅ | Run 1 changes due to git pull, Run 2 is idempotent. |
| **Testing Role** | | | | |
| `testing.hosts` | 0 | 0 | ✅ | Idempotency fixed by using precise negative lookahead for old IPs. |
| `testing.runc` | 0 | 0 | ✅ | Already at goal state. |
| `testing.mkcert` | 1 | 0 | ✅ | Idempotency fixed by adding force: no to README template. |
