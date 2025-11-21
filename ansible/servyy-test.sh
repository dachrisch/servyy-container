#!/bin/zsh
set -x
ansible-playbook servyy.yml -i testing --skip-tags system.swap,ubuntu_pro "$@"
