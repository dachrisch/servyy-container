#!/bin/bash

pushd /code
git pull
BUILD_PATH=/build yarn build
