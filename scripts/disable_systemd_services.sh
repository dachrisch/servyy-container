#!/bin/bash

system_path=~/.config/systemd/user
for service in ../systemd/docker-*;do
	service_name=$( basename $service )
	service_path=$( realpath $service )
	
	systemctl --user stop $service_name
	systemctl --user disable $service_name
done