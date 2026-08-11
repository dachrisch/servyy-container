# Alibaba Cloud Model Studio Provider for OpenCode

**Date:** 2026-08-11
**Status:** ✅ Completed, deployed to production
**Commits:** `63a321c`, `e38af2d`, `5528ce9`, `1c9c167`, `2662f55`, `0436e9c`

## Problem

Added Alibaba Cloud Model Studio (DashScope) as a provider to the OpenCode instance on `lehel.xyz` to enable Qwen models (`qwen3.7-max`, `qwen3.7-flash`, `qwen3.6-plus`).

## Changes

- Added `bailian-payg` provider to `opencode/scripts/opencode.json.template`
- Added `DASHSCOPE_API_KEY` to `ansible/plays/roles/docker_service/templates/opencode/.env.j2`
- Added `dashscope_api_key` to `ansible/plays/vars/secrets.yml`
- Updated `opencode/scripts/startup.sh` to include `$DASHSCOPE_API_KEY` in `envsubst`

## Iterations

Several iterations were needed to get the provider configuration correct:

1. **Initial attempt**: Used `@ai-sdk/anthropic` with `https://dashscope.aliyuncs.com/apps/anthropic/v1` — failed with "invalid api-key" because the key is for the OpenAI-compatible API, not Anthropic-compatible.

2. **Second attempt**: Switched to `openai` npm package — failed with "Failed to initialize provider: bailian-payg" because `openai` is not a valid OpenCode provider npm package.

3. **Third attempt**: Used `@ai-sdk/openai-compatible` with workspace ID extracted from API key (`H.YXDDYY`) — failed with `ERR_TLS_CERT_ALTNAME_INVALID` because the TLS cert uses lowercase.

4. **Fourth attempt**: Lowercased workspace ID to `h.yxddyy` — still failed because the actual workspace ID is different from what's embedded in the API key.

5. **Final fix**: Used the correct workspace ID `ws-b3cfk1t33tp7pr99` from the Model Studio console with baseURL `https://ws-b3cfk1t33tp7pr99.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`.

## Final Configuration

```json
{
  "bailian-payg": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "Alibaba Cloud Model Studio",
    "options": {
      "baseURL": "https://ws-b3cfk1t33tp7pr99.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
      "apiKey": "$DASHSCOPE_API_KEY"
    },
    "models": {
      "qwen3.7-max": { "name": "Qwen3.7 Max", "options": { "thinking": { "type": "enabled", "budgetTokens": 8192 } } },
      "qwen3.7-flash": { "name": "Qwen3.7 Flash", "options": { "thinking": { "type": "enabled", "budgetTokens": 8192 } } },
      "qwen3.6-plus": { "name": "Qwen3.6 Plus", "options": { "thinking": { "type": "enabled", "budgetTokens": 8192 } } }
    }
  }
}
```

## Lessons Learned

- The API key format `sk-ws-<workspaceId>...` contains a workspace identifier but it may not match the actual workspace ID shown in the console.
- Always verify the workspace ID and API host from the Model Studio console directly.
- OpenCode requires `@ai-sdk/openai-compatible` for OpenAI-compatible endpoints, not `openai`.
- Server updates must go through Ansible or `git pull` — manual `docker exec` edits are ephemeral.
