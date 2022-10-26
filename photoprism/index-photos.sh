#!/bin/zsh

pushd $HOME/photoprism
current_path=$( date +"cloudy/%Y/%m" )
docker-compose exec -T photoprism photoprism index $current_path
