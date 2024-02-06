#!/bin/sh
NAME=scitq-worker
TAG=1.2

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}