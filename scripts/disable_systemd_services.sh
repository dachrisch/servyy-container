#!/bin/bash

system_path=~/.config/systemd/user
for service in ${system_path}/docker-*;do
	service_name=$( basename $service )

	systemctl --user stop $service_name
	systemctl --user disable $service_name
done
