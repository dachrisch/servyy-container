# -*- coding: utf-8 -*-
# Copyright: (c) 2025, Vaultwarden Lookup Plugin
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
name: vaultwarden
author: Claude Code
short_description: Fetch secrets from Vaultwarden vault
description:
  - This lookup returns secrets from a Vaultwarden vault using the Bitwarden CLI (bw).
  - Authenticates using API key (client credentials OAuth).
  - Unlocks vault with master password.
  - Caches session for performance (one unlock per playbook run).
options:
  _terms:
    description: Item name to fetch from Vaultwarden (e.g., 'apps/test/leaguesphere/db_credentials').
    required: True
  field:
    description: Field to extract from the item (default 'password'). For login items use 'username', 'password', 'uris', 'totp', or custom field names.
    type: str
    default: 'password'
  wantlist:
    description: Unused, kept for Ansible compatibility.
    type: bool
    default: False
notes:
  - Requires bitwarden CLI (bw) installed on the control node.
  - Requires vaultwarden variable dict with server_url, api_client_id, api_client_secret, master_password.
  - SSL certificates Set NODE_EXTRA_CA_CERTS environment variable for self-signed certs (mkcert).
requirements:
  - bitwarden CLI (bw)
  - jq (for JSON parsing)
"""

EXAMPLES = r"""
# Fetch password from login item
- debug:
    msg: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='password') }}"

# Fetch username from login item
- debug:
    msg: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='username') }}"

# Fetch custom field from item
- debug:
    msg: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='host') }}"

# Use in variable assignment
- set_fact:
    db_password: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='password') }}"
    db_username: "{{ lookup('vaultwarden', 'apps/test/leaguesphere/db_credentials', field='username') }}"
"""

RETURN = r"""
_list:
    description: Value of the requested field from the Vaultwarden item.
    type: list
    elements: str
"""

import os
import json
import subprocess
from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.module_utils._text import to_text


class LookupModule(LookupBase):
    """Vaultwarden lookup plugin to fetch secrets using bw CLI."""

    _bw_session = None
    _bw_configured = False
    _mkcert_ca = None

    def run(self, terms, variables=None, **kwargs):
        """
        Main lookup method.

        Args:
            terms: List of item names to look up
            variables: Ansible variables dict
            **kwargs: Additional options (field, etc.)

        Returns:
            List of secret values
        """
        if not terms:
            raise AnsibleError("vaultwarden lookup requires at least one item name")

        # Get options
        field = kwargs.get('field', 'password')

        # Get vaultwarden config from variables
        if not variables or 'vaultwarden' not in variables:
            raise AnsibleError("vaultwarden lookup requires 'vaultwarden' variable with server config")

        # Determine environment (test vs prod) based on inventory
        inventory_hostname = variables.get('inventory_hostname', '')
        vw_config = None

        if 'test' in inventory_hostname or inventory_hostname.endswith('.lxd'):
            if 'test' in variables['vaultwarden']:
                vw_config = variables['vaultwarden']['test']
        elif 'prod' in inventory_hostname:
            if 'prod' in variables['vaultwarden']:
                vw_config = variables['vaultwarden']['prod']

        # Default to test if not determined
        if not vw_config and 'test' in variables['vaultwarden']:
            vw_config = variables['vaultwarden']['test']

        if not vw_config:
            raise AnsibleError("Could not determine vaultwarden config (test/prod)")

        # Ensure session is initialized
        if not self._bw_session:
            self._ensure_bw_session(vw_config, variables)

        # Fetch secrets for all terms
        results = []
        for term in terms:
            value = self._get_secret(term, field, vw_config)
            results.append(value)

        return results

    def _ensure_bw_session(self, vw_config, variables):
        """Initialize Bitwarden CLI session (config, login, unlock)."""

        # Get mkcert CA path for SSL - check multiple locations
        mkcert_ca = None

        # 1. Check if NODE_EXTRA_CA_CERTS is already set in environment
        if 'NODE_EXTRA_CA_CERTS' in os.environ:
            mkcert_ca = os.environ['NODE_EXTRA_CA_CERTS']

        # 2. Check for local CA (control machine) - fetched by mkcert.yml
        if not mkcert_ca or not os.path.exists(mkcert_ca):
            local_ca = '/tmp/servyy-test-ca.pem'
            if os.path.exists(local_ca):
                mkcert_ca = local_ca

        # 3. Fall back to server path (when running on server)
        if not mkcert_ca or not os.path.exists(mkcert_ca):
            if 'mkcert' in variables and 'cert_dir' in variables['mkcert']:
                server_ca = os.path.join(variables['mkcert']['cert_dir'], 'rootCA.pem')
                if os.path.exists(server_ca):
                    mkcert_ca = server_ca

        # Store CA path for reuse in _get_secret
        self._mkcert_ca = mkcert_ca if (mkcert_ca and os.path.exists(mkcert_ca)) else None

        env = os.environ.copy()
        if self._mkcert_ca:
            env['NODE_EXTRA_CA_CERTS'] = self._mkcert_ca

        # 1. Configure server (only once)
        if not self._bw_configured:
            # Logout first to allow server reconfiguration
            try:
                self._run_command(['bw', 'logout'], env=env, check_rc=False)
            except subprocess.CalledProcessError:
                # Ignore error - may not be logged in
                pass

            self._run_command(['bw', 'config', 'server', vw_config['server_url']], env=env)
            self._bw_configured = True

        # 2. Login with API key
        env['BW_CLIENTID'] = vw_config['api_client_id']
        env['BW_CLIENTSECRET'] = vw_config['api_client_secret']

        try:
            self._run_command(['bw', 'login', '--apikey'], env=env, check_rc=False)
        except subprocess.CalledProcessError:
            # Ignore error - may already be logged in
            pass

        # 3. Unlock vault and get session token
        if 'master_password' not in vw_config or not vw_config['master_password']:
            raise AnsibleError("Vaultwarden master password not provided in vw_config")

        env['BW_PASSWORD'] = vw_config['master_password']
        result = self._run_command(['bw', 'unlock', '--passwordenv', 'BW_PASSWORD', '--raw'], env=env)

        self._bw_session = result.strip()
        if not self._bw_session:
            raise AnsibleError("Failed to get Bitwarden session token")

    def _get_secret(self, item_name, field, vw_config):
        """
        Fetch a secret from Vaultwarden.

        Args:
            item_name: Name of the item (e.g., 'infrastructure/test/storagebox/credentials')
                      Will be prefixed with 'servyy/servyy-{env}/' automatically
            field: Field to extract ('password', 'username', or custom field name)
            vw_config: Vaultwarden configuration dict

        Returns:
            Secret value as string
        """
        # Determine environment from server_url
        environment = 'test' if 'test' in vw_config['server_url'] else 'prod'

        # Add servy prefix to item name
        full_item_name = f"servy/servy-{environment}/{item_name}"

        # Use mkcert CA for SSL if available (set in _ensure_bw_session)
        env = os.environ.copy()
        if self._mkcert_ca:
            env['NODE_EXTRA_CA_CERTS'] = self._mkcert_ca

        # Search for item by name
        cmd = ['bw', 'list', 'items', '--search', full_item_name, '--session', self._bw_session]
        result = self._run_command(cmd, env=env)

        try:
            items = json.loads(result)
        except json.JSONDecodeError as e:
            raise AnsibleError(f"Failed to parse bw output: {e}")

        if not items:
            raise AnsibleError(f"Item '{full_item_name}' not found in Vaultwarden")

        # Use exact match if multiple results
        item = None
        for i in items:
            if i.get('name') == full_item_name:
                item = i
                break

        if not item:
            item = items[0]  # Fallback to first result

        # Extract field value
        value = None

        # Standard login fields
        if field == 'password':
            value = item.get('login', {}).get('password')
        elif field == 'username':
            value = item.get('login', {}).get('username')
        elif field == 'uris':
            uris = item.get('login', {}).get('uris', [])
            value = uris[0]['uri'] if uris else None
        elif field == 'totp':
            value = item.get('login', {}).get('totp')
        elif field == 'notes':
            value = item.get('notes')
        else:
            # Check custom fields
            fields = item.get('fields', [])
            for f in fields:
                if f.get('name') == field:
                    value = f.get('value')
                    break

        if value is None:
            raise AnsibleError(f"Field '{field}' not found in item '{full_item_name}'")

        return value

    def _run_command(self, cmd, env=None, check_rc=True):
        """
        Run a command and return stdout.

        Args:
            cmd: Command list to run
            env: Environment dict
            check_rc: Whether to check return code

        Returns:
            Command stdout as string

        Raises:
            AnsibleError: If command fails and check_rc=True
        """
        try:
            result = subprocess.run(
                cmd,
                env=env or os.environ.copy(),
                capture_output=True,
                text=True,
                check=check_rc
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise AnsibleError(f"Command failed: {' '.join(cmd)}\nError: {e.stderr}")
        except FileNotFoundError:
            raise AnsibleError(f"Command not found: {cmd[0]}. Ensure bitwarden CLI (bw) is installed.")
