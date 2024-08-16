#!/bin/bash

find .. -name docker-compose.yml -type f -print0 | xargs -0 -I {} sh -c 'echo "Directory: $(dirname {})" && docker compose -f {} up -d'
