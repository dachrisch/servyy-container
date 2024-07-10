#!/bin/zsh
set -x
ansible-playbook servyy.yml -i production "$@"
