# Staging Environment File Naming Fix - 2026-05-31

## Problem

Test container deployment failed during staging configuration with error:
```
env file /var/jail/home/leaguesphere/container-stage/deployed/.env.staging not found
```

The docker-compose.staging.yaml expected `.env.staging` but the Ansible playbook was creating `.env` (without suffix).

## Root Cause

In `ansible/plays/leaguesphere.yml` line 60, the staging deployment role was hardcoded:
```yaml
docker_env_file: ".env"
```

This overrode the default logic in `roles/ls_app/tasks/env.yaml` that should append the `env_suffix` defined in `secret_stage.yaml`:
```yaml
env_suffix: .staging
```

The hardcoded value prevented the correct filename `.env.staging` from being generated.

## Solution

Removed the hardcoded `docker_env_file: ".env"` from the staging deployment in `leaguesphere.yml`.

**Changed:**
```yaml
- role: ls_app
  vars:
    container_dir: "{{ (ssh_chroot_jail_path, 'home', ls.user, 'container-stage') | path_join }}"
    ls_vars_file: "secret_stage.yaml"
    deploy_containers: true
    docker_env_file: ".env"  # ❌ REMOVED THIS LINE
```

**To:**
```yaml
- role: ls_app
  vars:
    container_dir: "{{ (ssh_chroot_jail_path, 'home', ls.user, 'container-stage') | path_join }}"
    ls_vars_file: "secret_stage.yaml"
    deploy_containers: true
```

Now the default logic works correctly:
- `docker_env_file | default('.env' ~ (app.env_suffix | default('')))`
- With `env_suffix: .staging`, creates `.env.staging` ✅

## Verification

Test deployment with fix:
```bash
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh --skip-tags user.docker.services.start --skip-tags restic
```

Result: **SUCCESS** (262 ok, 37 changed, 0 failed, 102 skipped)

Files created on test environment:
```
-rw-r--r-- .env              (old, from previous run)
-rw-r--r-- .env.staging      ✅ (correctly created in latest run)
-rw-r--r-- ls.env.staging
-rw-r--r-- ls.env.staging.template
```

## Deployment

- Commit: `82a403c` - fix: remove hardcoded docker_env_file for staging deployment
- Pushed to: origin/master
- Status: Ready for production deployment

## Files Changed

- `ansible/plays/leaguesphere.yml` - removed hardcoded docker_env_file override

## Lesson

**Environment file naming with suffixes:**
- Don't hardcode `docker_env_file` in role vars if you want env_suffix to work
- Let the template defaults handle filename generation: `.env` + suffix
- Verify suffix is defined in the app's secret_*.yaml file
- Test on servyy-test.lxd before production deployment

## Related

- See `feedback_deployment_git_pull.md` for deployment workflow
- See `feedback_orphaned_containers.md` for container cleanup before redeployment
