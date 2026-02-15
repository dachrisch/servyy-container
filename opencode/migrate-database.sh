#!/bin/bash
set -e

echo "OpenCode Database Migration Script"
echo "==================================="
echo ""
echo "This script will:"
echo "1. Extract the SQLite database from the running container"
echo "2. Create the db directory on the host"
echo "3. Restart the container with persistent database storage"
echo ""

# Check if container is running
if ! docker ps | grep -q opencode.app; then
    echo "ERROR: opencode.app container is not running"
    exit 1
fi

# Create db directory
echo "Creating db directory..."
mkdir -p ./db

# Extract database from container
echo "Extracting database from container..."
docker cp opencode.app:/root/.local/share/opencode/opencode.db ./db/opencode.db

# Verify extraction
if [ -f ./db/opencode.db ]; then
    echo "✓ Database extracted successfully"
    ls -lh ./db/opencode.db
else
    echo "ERROR: Database extraction failed"
    exit 1
fi

# Set correct permissions
echo "Setting permissions..."
chown -R $(id -u):$(id -g) ./db

echo ""
echo "Migration preparation complete!"
echo ""
echo "Next steps:"
echo "1. Deploy updated docker-compose.yml (ansible/servyy.sh)"
echo "2. Container will restart with persistent database storage"
echo "3. Verify the database is accessible"
