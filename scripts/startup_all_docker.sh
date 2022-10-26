#!/bin/zsh

services=(traefik photoprism bumbleflies achim-hoefer git)

for service in ${services[@]};do
  pushd $service
  docker-compose up -d
  popd
done

