#!/bin/zsh
set -x
ansible-playbook servyy.yml -i testing --extra-vars=root_user=ubuntu "$@"
