#!/bin/zsh

echo 'Cleaning up journal files...'
sudo journalctl --vacuum-size=1G

echo 'Cleaning up unused docker images...'
docker image prune -a
docker system prune -a

echo 'Removing old kernel versions...'
remove_old_kernels.sh
