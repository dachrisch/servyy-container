#!/bin/bash

find .. \( -name docker-compose.yml -o -name docker-compose.yaml \) -type f -print0 | xargs -0 -I {} sh -c 'echo "Directory: $(dirname {})" && docker compose -f {} up -d'
