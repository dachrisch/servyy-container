#!/bin/bash
set -e

echo "Starting Firefly III import from $(date)"

curl -X POST "${FIREFLY_III_URL}/autoupload?secret=${AUTO_IMPORT_SECRET}" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${FIREFLY_III_ACCESS_TOKEN}" \
  -F "json=@/import/import_config.json"

echo "Import completed at $(date)"