#!/bin/zsh

for year in {2004..2022}; do
  for month in {01..12}; do
    echo "pushd $HOME/servyy-container/photoprism;docker-compose exec -T photoprism photoprism index $year/$month" | batch
  done
done
