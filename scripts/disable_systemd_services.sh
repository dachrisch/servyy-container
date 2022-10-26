#!/bin/bash

system_path=~/.config/systemd/user
for service in ../systemd/docker-*.service;do
	service_name=$( basename $service )
	service_path=$( realpath $service )
	
	echo systemctl --user stop $service_name
	echo systemctl --user disable $service_name
	echo rm $system_path/$service_name
done
