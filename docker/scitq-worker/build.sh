#!/bin/sh
NAME=scitq-worker
TAG=1.3.1

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}