# AGENTS.md - Infrastructure Container Development Guide

This file contains build/lint/test commands and code style guidelines for agentic coding agents working in this repository.

## Build/Lint/Test Commands

### Ansible Development
```bash
# Syntax check all playbooks
cd ansible && ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/system.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/user.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/testing.yml --syntax-check -i testing
cd ansible && ansible-playbook plays/leaguesphere.yml --syntax-check -i testing

# Lint Ansible playbooks
cd ansible && ansible-lint --force-color --show-relpath

# Molecule Testing (REQUIRED for new features)
cd ansible/plays/roles/{role}/ && molecule test --scenario-name {scenario}

# Available scenarios:
# system: minimal, core, with-docker, default
# user: default, docker-only  
# testing: default

# Run all scenarios in parallel
cd ansible && molecule test

# Single test example
cd ansible/plays/roles/system && molecule test --scenario-name minimal
```

### Python Development (Custom Modules)
```bash
# Install dependencies
cd ansible && pip install -r requirements.txt

# Lint Python code
cd ansible && flake8 library/ --max-line-length=120
cd ansible && pylint library/json_patch.py --disable=C0103,R0912,R0915,C0209,W0613,R1705,W0707,R1720,R1710,W0612,R0911,C0116,R1735 --fail-under=6.0

# Run unit tests
cd ansible/library && python -m unittest discover -s tests -p "test_*.py" -v
```

### YAML Development
```bash
# Lint YAML files
cd ansible && yamllint -c ../.yamllint.yml .
```

### Docker Development
```bash
# Build and test docker-compose services
cd {service} && docker-compose config --quiet
cd {service} && docker-compose up --build --no-start
```

## Code Style Guidelines

### General Principles
- **Test-First Development**: Always write Molecule tests before implementing new Ansible features
- **Security First**: Never commit unencrypted secrets or credentials
- **Idempotency**: All Ansible tasks must be idempotent
- **Documentation**: Update history/YYYY-MM-DD_description.md for major changes

### Ansible Style
```yaml
# Use 2-space indentation
- name: Descriptive task name
  module_name:
    key: value
  register: task_output
  tags:
    - appropriate.tag
  when: condition | default(false)
  notify: handler_name

# Use include_tasks over import_tasks for dynamic includes
- include_tasks: tasks/file.yml
  vars:
    custom_var: value
  tags:
    - dynamic.tag
```

### YAML Formatting
- Max line length: 160 characters (warning level)
- 2-space indentation
- Consistent sequence indentation
- Use comments sparingly, 1 space from content
- Document start (---) optional for single-document files

### Python Style (Custom Modules)
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Module docstring explaining purpose."""

import json
import os
import sys
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

class ExampleClass:
    """Class docstring explaining purpose."""
    
    def __init__(self, param):
        """Initialize with parameters."""
        self.param = param
        self._private_var = None
    
    def public_method(self):
        """Public method description."""
        return self.param
    
    def _private_method(self):
        """Private method description."""
        return self._private_var
```

### Naming Conventions
- **Files**: kebab-case (e.g., `docker_services.yml`, `json_patch.py`)
- **Variables**: snake_case (e.g., `create_user`, `docker_services`)
- **Functions/Methods**: snake_case with descriptive names
- **Classes**: PascalCase (e.g., `JSONPatcher`, `PatchManager`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `ANSIBLE_METADATA`, `DOCUMENTATION`)
- **Tags**: kebab-case with descriptive names (e.g., `user.docker.services`)

### Error Handling
```yaml
# Ansible tasks should handle errors gracefully
- name: Task with error handling
  module_name:
    key: value
  register: result
  ignore_errors: yes  # Only when appropriate
  failed_when: result.failed and 'specific_error' not in result.msg
  changed_when: result.changed
```

```python
# Python error handling
class CustomError(Exception):
    """Custom exception class."""
    pass

def risky_operation():
    try:
        # Operation that might fail
        result = some_function()
        return result
    except SpecificError as e:
        # Handle specific error
        raise CustomError(f"Operation failed: {e}") from e
    except Exception as e:
        # General error handling
        raise CustomError(f"Unexpected error: {e}") from e
```

### Import Organization
```python
# Standard library imports first
import json
import os
import sys
import unittest

# Third-party imports next
from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes, to_native

# Local imports last
from json_patch import JSONPatcher
```

### Documentation Standards
```yaml
# Ansible tasks should have clear documentation
- name: Configure system packages
  apt:
    name: "{{ packages }}"
    state: present
  vars:
    packages:
      - nginx
      - fail2ban
  tags:
    - system.packages
  when: ansible_os_family == 'Debian'
  notify: restart nginx
  
  # Add comments for complex logic
  # This task installs essential security packages
  # and notifies handlers for service restarts
```

### Git Workflow
```bash
# Feature branch naming
git checkout -b claude/feature-name

# Commit message format
feat: add new service deployment
git commit -m "feat: description"

# Before production deployment
cd scripts && ./setup_test_container.sh
cd ../ansible && ./servyy-test.sh

# After successful test deployment
cd ansible && ./servyy.sh --limit lehel.xyz
```

### Security Guidelines
- **Never** commit unencrypted secrets
- **Always** use git-crypt for encrypted files
- **Validate** git-crypt status before committing: `git-crypt status`
- **Use** environment variables for sensitive configuration
- **Follow** principle of least privilege for all service accounts

### Testing Requirements
- **Molecule tests required** for all new Ansible features
- **Unit tests required** for all custom Python modules
- **Integration tests** for complex service deployments
- **Test on servyy-test.lxd** before production deployment
- **CI validation** must pass before merging

### Performance Considerations
- Use `async` and `poll` for long-running tasks
- Implement proper error handling and retries
- Use `check_mode` for read-only operations
- Optimize Docker image sizes and service configurations
- Monitor resource usage with Prometheus/Grafana stack

### Docker Service Guidelines
```yaml
# Service configuration standards
services:
  app:
    container_name: ${COMPOSE_PROJECT_NAME}.app
    image: image:tag
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.${SERVICE_NAME}.rule=Host(`${SERVICE_HOST}`)"
      - "traefik.http.routers.${SERVICE_NAME}.entrypoints=websecure"
      - "traefik.http.routers.${SERVICE_NAME}.tls.certresolver=letsencryptdnsresolver"
    environment:
      - KEY=value
    volumes:
      - type: bind
        source: ./data
        target: /app/data
        read_only: true
```

### Emergency Procedures
- **Never** make manual changes to production servers
- **Always** replicate manual changes in git repo
- **Test** emergency fixes on test environment first
- **Document** all emergency procedures in history logs
- **Follow** standard deployment workflow after emergency fixes

## Critical Paths
- **Ansible playbooks**: `ansible/servyy.yml`, `ansible/plays/*.yml`
- **Encrypted files**: `ansible/plays/vars/secrets.yml`, `ansible/plays/vars/secret_*.yaml`
- **Custom modules**: `ansible/library/`, `ansible/library/tests/`
- **Docker services**: `*/docker-compose.yml`
- **Molecule tests**: `ansible/plays/roles/*/molecule/`

## Validation Commands
```bash
# Pre-commit validation
git-crypt status
ansible-playbook servyy.yml --syntax-check -i testing
cd ansible && yamllint -c ../.yamllint.yml .
cd ansible && flake8 library/ --max-line-length=120
cd ansible/library && python -m unittest discover -s tests -p "test_*.py" -v
```

## Notes for Agents
- This is a **production infrastructure** repository - changes have real-world impact
- **Test-first approach** is mandatory for all infrastructure changes
- **Security** is paramount - never compromise encryption or access controls
- **Documentation** is critical - update history logs for all significant changes
- **Rollback procedures** should be considered for all major deployments