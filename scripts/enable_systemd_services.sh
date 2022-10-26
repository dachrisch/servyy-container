#!/bin/bash

system_path=~/.config/systemd/user
for service in ../systemd/docker-*;do
	service_name=$( basename $service )
	service_path=$( realpath $service )
	
	ln -s $service_path $system_path/$service_name
	systemctl --user enable $service_name
done
