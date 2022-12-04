FROM alpine:3.17

RUN apk add --no-cache python3 wget  gcc python3-dev libc-dev linux-headers && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python3 get-pip.py && \
    pip install scitq && \
    apk del gcc python3-dev libc-dev linux-headers wget && \
    rm get-pip.py

ENV FLASK_APP=scitq.server
ENV SQLALCHEMY_DATABASE_URI=sqlite:////var/lib/scitq/scitq.db
ENV DEBUG=1

VOLUME ["/var/lib/scitq"]
ENTRYPOINT [ "flask", "run", "--host=0.0.0.0" ]

EXPOSE 5000

# docker run --rm -it miniscitq sh -c "FLASK_APP=scitq.server DEBUG=1 flask run"
