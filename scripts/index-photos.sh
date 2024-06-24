#!/bin/zsh

pushd $HOME/servyy-container/photoprism
current_path=$( date +"%Y/%m" )
docker compose exec -T photoprism photoprism index $current_path
