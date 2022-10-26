#!/bin/zsh

services=(traefik photoprism bumbleflies achim_hoefer git)

for service in ${services[@]};do
  pushd $service
  docker-compose up -d
done

