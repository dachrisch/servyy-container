#!/bin/zsh

services=(traefik photoprism bumbleflies achim-hoefer git portainer)

for service in ${services[@]};do
  pushd ../$service
  docker-compose down
  popd
done

