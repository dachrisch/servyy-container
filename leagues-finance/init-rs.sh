#!/bin/bash
# Wait for mongo to be ready
echo "Waiting for MongoDB to start..."
until docker exec leagues-finance.mongo mongosh --eval "db.adminCommand('ping')" &>/dev/null; do
  sleep 1
done

echo "Initializing replica set..."
docker exec leagues-finance.mongo mongosh --eval 'rs.initiate({
  _id: "rs0",
  members: [{ _id: 0, host: "localhost:27017" }]
})'
