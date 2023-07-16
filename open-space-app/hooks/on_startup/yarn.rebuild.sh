#!/bin/bash

pushd /code
git pull
yarn
BUILD_PATH=/build yarn build
