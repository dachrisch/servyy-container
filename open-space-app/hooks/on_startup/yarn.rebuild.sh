#!/bin/bash

pushd /code || exit
git pull
yarn
BUILD_PATH=/build yarn build
