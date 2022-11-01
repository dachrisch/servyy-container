#!/bin/bash

pushd /code
git pull
bundle install
bundle exec jekyll build -s /code -d /site
