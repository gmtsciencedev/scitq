#!/bin/sh
NAME=scitq-worker
TAG=1.0rc11

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}