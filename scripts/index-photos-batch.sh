#!/bin/zsh

touch $HOME/reindex.log
truncate -s0 $HOME/reindex.log
for year in {2004..2022}; do
  for month in {01..12}; do
    echo "pushd $HOME/servyy-container/photoprism && docker-compose exec -T photoprism photoprism index $year/$month >> $HOME/reindex.log 2>&1" | batch
  done
done
