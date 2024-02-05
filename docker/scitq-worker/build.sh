#!/bin/sh
NAME=scitq-worker
TAG=1.2rc5

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}