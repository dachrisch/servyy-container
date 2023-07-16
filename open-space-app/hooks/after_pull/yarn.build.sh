#!/bin/bash

pushd /code || exit
BUILD_PATH=/build yarn build
