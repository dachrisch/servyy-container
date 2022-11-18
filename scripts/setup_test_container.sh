#!/bin/zsh

set -e
instance=servyy-test
hostname="${instance}.lxd"
retries=10

# https://kerneltalks.com/howto/how-to-disable-iptables-firewall-temporarily/
if [[ $(sudo iptables -L FORWARD | wc -l) -gt 2 ]];then
  echo 'cleaning iptables'
  sudo iptables-save | tee ".backup/iptables_$(date +%s).backup" > /dev/null
  sudo iptables -F
  sudo iptables -X
  sudo iptables -P FORWARD ACCEPT
  sudo iptables -P OUTPUT ACCEPT
  sudo iptables -P INPUT ACCEPT
fi

if ! lxc profile get $instance name  > /dev/null 2>&1;then
  echo "creating server profile [$instance]"
  lxc profile create $instance
  cat $instance.yaml | lxc profile edit $instance
fi

if ! lxc info $instance > /dev/null 2>&1;then
  echo "creating server [$instance]"
  lxc launch -p $instance ubuntu:22.04 $instance
  lxc config set $instance security.privileged true
elif [[ ! $(lxc info $instance|grep 'Status:') =~ 'RUNNING' ]];then
  echo "starting server [$instance]"
  lxc start $instance
fi

# https://linuxcontainers.org/lxd/docs/master/howto/network_bridge_resolved/
if ! host $hostname > /dev/null 2>&1;then
  echo 'enable local name resolution'
  sudo resolvectl dns lxdbr0 "$(lxc network get lxdbr0 ipv4.address|cut -d'/' -f1)"
  sudo resolvectl domain lxdbr0 "~$(lxc network get lxdbr0 dns.domain)"
  if ssh-keygen -f "$HOME/.ssh/known_hosts" -F "$hostname" > /dev/null;then
    echo 'removing old known_hosts key'
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$hostname"
  fi
fi

while ! host $hostname > /dev/null 2>&1;do
  echo -n "$retries..."
  sleep 2
  ((retries--))
  if [[ $retries -lt 1 ]];then
    echo "FAILED"
    break
  fi
done
host $hostname