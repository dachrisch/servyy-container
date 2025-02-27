#!/bin/zsh

instance="servyy-test"
storage_pool=$(yq '.devices.root.pool' $instance.yaml | tr -d '"')
bridge_network=$(yq '.devices.eth0.parent' $instance.yaml | tr -d '"')

lxc delete --force $instance
lxc profile delete $instance
lxc storage delete $storage_pool
# TODO: cannot delete lxc network delete $bridge_network
