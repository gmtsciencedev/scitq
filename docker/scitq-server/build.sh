#!/bin/sh
NAME=scitq-server
TAG=1.3.1

unameOut="$(uname -s)"
case "${unameOut}" in
    Linux*)     EXTRATAG='';;
    Darwin*)    EXTRATAG='-arm';;
    *)          echo 'Unsupported builder' && exit 1;;
esac

docker build -t gmtscience/${NAME}:${TAG}${EXTRATAG} .
docker push gmtscience/${NAME}:${TAG}${EXTRATAG}

docker tag gmtscience/${NAME}:${TAG} gmtscience/${NAME}:latest${EXTRATAG}
docker push gmtscience/${NAME}:latest${EXTRATAG}