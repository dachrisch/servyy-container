#!/bin/bash

system_path=~/.config/systemd/user
for service in ../systemd/docker-*.service;do
	service_name=$( basename $service )
	service_path=$( realpath $service )
	
	echo ln -s $service_path $system_path/$service_name
	echo systemctl --user enable $service_name
done
