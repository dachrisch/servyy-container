---
name: leaguesphere-maintenance-toggle
description: How to toggle LeagueSphere maintenance mode via Django admin without container restart
source: auto-skill
extracted_at: '2026-07-14T18:11:01.000Z'
---

# LeagueSphere Maintenance Mode Admin Toggle

## Context
LeagueSphere is a Django app (`github.com/dachrisch/league-manager`) deployed on `lehel.xyz`. Maintenance mode was previously toggled only by direct DB injection into `league_manager_siteconfiguration.maintenance_mode` + container restart to clear the `LocMemCache`.

## How it works now

The app has a `SiteConfiguration` model with `maintenance_mode` (BooleanField). A `MaintenanceModeMiddleware` checks this on every request, caching the result under key `site_maintenance_config` (6M second TTL). A `post_save` signal clears this cache automatically when the model is saved.

### Admin toggle (new — code change in `league_manager/admin.py`)

```python
@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ("maintenance_mode_display", "maintenance_pages_count")
    actions = ["enable_maintenance", "disable_maintenance"]

    # Toggle URL: /admin/league_manager/siteconfiguration/toggle-maintenance/
```

**Usage:**
1. Login to Django admin: `https://leaguesphere.app/admin/`
2. Go to **Site configurations**
3. Either:
   - Select row → Action: "Enable maintenance mode" / "Disable maintenance mode" → Go
   - Visit `/admin/league_manager/siteconfiguration/toggle-maintenance/` for one-click flip

**No restart needed** — the `post_save` signal in `league_manager/signals.py` calls `cache.delete("site_maintenance_config")` automatically.

## Dev server spinup

The app repo has a `container/start_dev_server.sh` script. Quick start with SQLite demo mode:

```bash
cd league-manager
./container/start_dev_server.sh --demo
```

Or manually:
```bash
export DJANGO_SETTINGS_MODULE=league_manager.settings.demo
export SECRET_KEY='django-insecure-demo-key-for-local-testing'
export DEMO_MODE=True
uv sync --extra test
uv run python manage.py migrate --noinput
uv run python manage.py seed_demo_data
# Create admin user
echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', 'admin@example.com', 'admin')" | uv run python manage.py shell
uv run python manage.py runserver 0.0.0.0:8000 --insecure
```

Demo accounts: `admin@demo.local / DemoAdmin123!`, `referee@demo.local / DemoRef123!`, etc.

## Worktree setup for LeagueSphere app

The app lives in a separate repo. Create a worktree for local development:

```bash
# From the infrastructure repo
git -C /home/cda/dev/leaguesphere worktree add \
  /home/cda/dev/infrastructure/container/.worktrees/leaguesphere-master master
```

## Key files in app repo
- `league_manager/models.py` — `SiteConfiguration` model
- `league_manager/middleware/maintenance.py` — `MaintenanceModeMiddleware`
- `league_manager/signals.py` — `post_save` cache invalidation
- `league_manager/admin.py` — admin interface (extended with toggle)
- `league_manager/constants.py` — `MAINTENANCE_CONFIG_CACHE_KEY`
- `container/start_dev_server.sh` — dev server spinup script

## Lesson: Tests require LXC test DB
`pytest` tests for the app need a MySQL database running. The `container/spinup_test_db.sh` script sets this up on `servyy-test.lxd` (remote LXD container). Without it, tests fail with `OperationalError: Can't connect to MySQL server`. Use `--demo` mode for local dev with SQLite instead.
