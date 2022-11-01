#!/bin/bash

pushd /code
bundle exec jekyll build -s /code -d /site
