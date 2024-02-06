FROM alpine:3.17

RUN apk add --no-cache python3 wget  gcc python3-dev libc-dev linux-headers ansible supervisor uwsgi && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python3 get-pip.py && \
    pip install scitq==1.2 openstacksdk==0.61 pyuwsgi && \
    ansible-galaxy install rolehippie.mdadm && \
    ansible-galaxy collection install openstack.cloud:1.8.0 && \
    ansible-galaxy collection install azure.azcollection && \
    apk del gcc python3-dev libc-dev linux-headers wget && \
    rm get-pip.py

RUN scitq-manage ansible install
RUN mkdir /var/lib/scitq

COPY supervisord.conf /etc/supervisord.conf
COPY run_services.sh /usr/local/bin/

ENV SQLALCHEMY_DATABASE_URI=sqlite:////var/lib/scitq/scitq.db
ENV FLASK_APP=scitq.server
ENV PATH=/bin:/sbin:/usr/bin:/usr/local/bin
ENV SCITQ_SERVER=127.0.0.1
ENV SCITQ_SERVER_PROCESS=2
ENV SCITQ_PRODUCTION=1
ENV DEBUG=1
VOLUME ["/root/.ssh"]
ENTRYPOINT [ "sh", "/usr/local/bin/run_services.sh" ]

EXPOSE 5000

# docker run --rm -it miniscitq sh -c "FLASK_APP=scitq.server DEBUG=1 flask run"
