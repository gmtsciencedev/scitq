#!/bin/sh
NAME=scitq-server
TAG=1.3.1

docker build -t gmtscience/${NAME}:${TAG} .
docker push gmtscience/${NAME}:${TAG}

docker tag gmtscience/${NAME}:${TAG} gmtscience/${NAME}:latest
docker push gmtscience/${NAME}:latest