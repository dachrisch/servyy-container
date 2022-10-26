#!/bin/zsh

services=(traefik photoprism bumbleflies achim_hoefer git)

for service in ${services[@]};do
  systemctl --user start docker-$service
  systemctl --user -n0 status docker-$service
done

