#!/bin/zsh

function get_http_code() {
  domain=$1
  url=$2

  if [ -z "$url" ];then url="https://$domain";fi

  echo $( curl -k -Is -o /dev/null -w"%{http_code}" --resolve $domain:443:localhost $url )
}

test_domain() {
  domain=$1
  echo -n "testing [$domain]..."
  if [ "200" = $( get_http_code $domain) ];then
    echo "[OK]"
  else
    echo "[FAILED]"
  fi
}

test_domain www.xn--hfer-architekten-mwb.de
test_domain xn--hfer-architekten-mwb.de
test_domain achim.servyy.duckdns.org
test_domain bumbleflies.servyy.duckdns.org
test_domain git.servyy.duckdns.org
test_domain photoprism.servyy.duckdns.org
