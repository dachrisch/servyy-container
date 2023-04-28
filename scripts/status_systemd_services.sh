#!/bin/bash

system_path=~/.config/systemd/user
for service in ${system_path}/docker-*;do
	service_name=$( basename $service )

	echo "${service_name}...[$(systemctl --user is-active $service_name)]"
done
