#!/bin/sh
NAME=scitq-worker
TAG=1.2rc4

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}