#!/bin/bash

system_path=~/.config/systemd/user
for service in ${system_path}/docker-*;do
	service_name=$( basename $service )

	systemctl --user start $service_name
done
