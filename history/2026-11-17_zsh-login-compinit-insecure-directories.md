# ADR: Stop zsh's compinit from blocking every SSH login on both servers

**Date:** 2026-11-17
**Status:** Accepted
**Relates to:** ADR "Replicate codey.lehel.xyz onto an Oracle Always Free A1 instance",
`roles/user/tasks/includes/repository.yml` (the deploy checkout's umask contract)

## Context

Logging in over SSH to **both** `servy.lehel.xyz` and `codey.lehel.xyz` stopped at an
interactive prompt instead of a shell:

```
zsh compinit: insecure directories, run compaudit for list.
Ignore insecure directories and continue [y] or abort compinit [n]?
```

The shell waited for an answer, so every `ssh host` looked hung until someone typed `y`.
`compaudit` named the whole `~/.zprezto` tree (16 directories), all `cda:docker` and
`drwxrwxr-x` on servy / `drwxrwx---` on codey.

Two independent causes fed the same tree:

1. **The deploy checkout runs under `umask 007`.** `includes/repository.yml` deliberately
   fixes only *ownership* (its comment: "modes are left as the checkout produced them"),
   because the container repo holds git-crypt'd secrets that must stay `0660`/`0770`. The
   zprezto clone inherits the same `0770`, and zsh's `compinit` treats any `$fpath`
   directory writable by group or others as insecure. Nothing narrowed it, so the prompt
   came back on the first login after a deploy.
2. **`~/.zshrc` and `~/.zlogin` printed to the console during init.** `~/.zshrc` (a symlink
   into the `my-prezto` dotfiles repo) sourced `~/.atuin/bin/env` **unguarded** on line 79,
   duplicating the guarded source inside the atuin block. atuin 18.24.8 (codey) no longer
   writes that file, so codey additionally printed
   `~/.zshrc:79: no such file or directory`. `.zlogin`'s `atuin sync > /dev/null` left
   atuin's **stderr** progress on the console, which powerlevel10k's instant prompt captured
   as initialization output and answered with a 25-line "Console output during zsh
   initialization detected" warning on every login.

## Decision

Fix the permission cause **inside the checkout include**, not in the zprezto task file, and
clean up the two dotfiles that printed at login.

- `includes/repository.yml`: new task `Make [ {{remote_dir}} ] unwritable for group and
  others` (`chmod -R go-w`), gated on `secure_checkout_modes` (default `false`). The zprezto
  import in `tasks/main.yml` sets it `true`; the container repo import does not, so its
  `0660`/`0770` secret contract is untouched.
- `roles/user/tasks/atuin.yml`: own `~/.atuin/bin/env` explicitly (`copy`), because the
  newer cargo-dist installer no longer writes it and the install block is skipped once the
  binary is current — so a host could never regain the file.
- `my-prezto`: drop the duplicated bun block and the unguarded atuin source from
  `runcoms/zshrc`, and send atuin's stderr to `/dev/null` in `runcoms/zlogin` and
  `runcoms/zlogout`.

Placing the narrowing in the include rather than in `zprezto.yml` is the load-bearing
decision: `zprezto.yml` does not run on a `--tags user.repo.zpresto` deploy, and that is the
exact run that re-created the `0770` tree.

## Consequences

### Positive

- ✅ SSH login returns to a prompt immediately on both hosts; no `[y/n]` gate.
- ✅ The fix survives *every* checkout path, including tag-only deploys that skip the
  zprezto tasks.
- ✅ The p10k initialization warning and the atuin `no such file` / `Sync complete!` noise
  are gone, so login output is quiet again.
- ✅ The container repo's `0660`/`0770` secret contract is unchanged (`secure_checkout_modes`
  is opt-in).
- ✅ A molecule scenario now reproduces the umask and asserts no directory is group/world
  writable, so the regression is caught in CI.

### Negative / Tradeoffs

- ⚠️ The narrowing task reports `changed_when: false`: the checkout re-applies `0660` to
  every file it rewrites, so the `chmod` does real work on every run while the end state is
  stable. Same reasoning (and same choice) as the `chown` task directly above it.
- ⚠️ Modes differ per host (`755` on servy where `a+rX` had already run, `750` on codey).
  Both satisfy `compinit`; they are not normalised to one value.
- ⚠️ `~/.atuin/bin/env` is now owned by the role rather than by the installer, so an upstream
  change to that shim will not be picked up automatically.

### Implementation Details

**Files modified:**

- `ansible/plays/roles/user/tasks/includes/repository.yml` (MODIFY — new
  `secure_checkout_modes` task)
- `ansible/plays/roles/user/tasks/main.yml` (MODIFY — pass `secure_checkout_modes: true` to
  the zprezto import)
- `ansible/plays/roles/user/tasks/atuin.yml` (MODIFY — own `~/.atuin/bin/env`)
- `ansible/plays/roles/user/molecule/default/converge.yml` (MODIFY — simulate the umask,
  then re-run the checkout include the way a tag-only deploy does)
- `ansible/plays/roles/user/molecule/default/verify.yml` (MODIFY — assert no group/world
  writable directory under the checkout)
- `my-prezto` `runcoms/zshrc`, `runcoms/zlogin`, `runcoms/zlogout` (separate repo)

**Commits (my-prezto):**

- `14598428` fix(zshrc): drop the duplicated bun block and the unguarded atuin env source
- `7de915d6` fix(zlogin): send atuin sync progress to /dev/null as well
- `ed8d51c4` fix(zlogout): silence atuin sync progress on logout too

**Testing & Verification:**

- ✅ `compaudit` returns nothing on servy and codey; 0 group/world-writable directories.
- ✅ Interactive `ssh -tt` login + logout on both hosts: 0 lines matching
  `compinit|insecure|WARNING|ERROR|no such file|Sync complete`, prompt reached.
- ✅ Idempotency: two consecutive `--tags user.repo.zpresto` runs report `changed=0`.
- ✅ `yamllint`, `ansible-lint` (production profile) and `--syntax-check` pass.
- ⚠️ Molecule could not run locally (no Docker daemon on this workstation) and
  `servyy-test.lxd` did not resolve, so the scenario is validated by CI, not here.

**Key Learnings:**

1. **`compinit` blocks, it does not just warn.** The message looks like a warning, but on a
   TTY it is a prompt that stops the shell — which is why it read as "login hangs".
2. **The fix must live where the mode is created.** The first attempt put the `chmod` in
   `zprezto.yml`; a later `--tags user.repo.zpresto` run re-widened the tree and brought the
   prompt back within minutes. The repository include is the only place every checkout path
   passes through.
3. **`chmod -c` is the honest idempotency signal, but the checkout defeats it.** The git
   module re-applies `umask 007` to files it rewrites on every run, so a mode-narrowing task
   legitimately reports a change forever; `changed_when: false` matches the neighbouring
   `chown`.
4. **`find -perm /022` matches symlinks.** Symlinks are always `0777`, so the assertion has
   to be `-type d -perm /022` — directories are what `compinit` inspects.
5. **Newer atuin installers stopped writing `~/.atuin/bin/env`.** servy's copy dated from
   18.24.3 (June); codey's 18.24.8 install has only the binary, so any unguarded source of
   that path errors on every login.
6. **powerlevel10k's instant-prompt warning is a console-output detector.** It reported
   atuin's *stderr* progress, not the `compinit` prompt; `POWERLEVEL9K_INSTANT_PROMPT=verbose`
   names the exact lines captured.

### Known Issues & Limitations

- The `user` role is not check-mode safe: `atuin.yml` skips its `getent` command in check
  mode and then fails resolving `atuin_home`. Pre-existing, unrelated to this change.
- The atuin `env` shim is now static content in the role; it must be updated by hand if
  upstream changes it.

## Alternatives Considered

### Alt A: `compinit -u` / `zstyle` to ignore insecure directories
Pros: one line, no permission changes.
Cons: explicitly disables the check that protects against a writable `$fpath` being used for
code execution; also edits the dotfiles for a server-side permission bug.
**Rejected.**

### Alt B: Change the deploy play's umask to `022`
Pros: fixes the root cause for every checkout at once.
Cons: the `0660`/`0770` modes on git-crypt'd secrets and container-consumed config are a
deliberate, documented contract; changing the umask would silently re-permission the
container repo and has already caused outages (nginx 403, grafana "permission denied").
**Rejected.**

### Alt C: Put the `chmod` in `roles/user/tasks/zprezto.yml`
Pros: keeps prezto concerns in the prezto task file.
Cons: does not run on `--tags user.repo.zpresto`, which is a normal deploy; verified to
reintroduce the bug minutes after the first fix.
**Rejected.**

### Alt D: Set `POWERLEVEL9K_INSTANT_PROMPT=quiet`
Pros: hides the p10k warning without touching `.zlogin`.
Cons: the warning was a symptom; the console output itself (atuin stderr) was the defect, and
hiding it would also hide future genuine init output.
**Rejected.**
