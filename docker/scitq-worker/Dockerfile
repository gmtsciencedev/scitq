FROM docker:20.10.21-dind-alpine3.17

RUN apk add --no-cache python3 wget  gcc python3-dev libc-dev linux-headers libffi-dev && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python3 get-pip.py && \
    pip install scitq==1.2 && \
    apk del gcc python3-dev libc-dev linux-headers wget && \
    rm get-pip.py

ENV SCITQ_SERVER=host.docker.internal
ENV STATUS=running
ENV SCITQ_FLAVOR=docker

VOLUME ["/scratch","/root/.aws"]

ENTRYPOINT (sleep 10 && scitq-worker -n ${NAME} -f ${SCITQ_FLAVOR} -s ${STATUS} ${SCITQ_SERVER} 1) &  /usr/local/bin/dockerd-entrypoint.sh
