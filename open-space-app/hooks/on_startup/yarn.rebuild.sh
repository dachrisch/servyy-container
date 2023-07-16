#!/bin/bash

pushd /code || exit
git pull
apk add yarn
yarn
BUILD_PATH=/build yarn build
