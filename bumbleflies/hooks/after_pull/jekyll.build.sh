#!/bin/bash

pushd /code
bundle install
bundle exec jekyll build -s /code -d /site --incremental
