FROM alpine:3.17

RUN apk add --no-cache python3 wget  gcc python3-dev libc-dev linux-headers ansible && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python3 get-pip.py && \
    pip install scitq==1.0 openstacksdk==0.61 && \
    ansible-galaxy install rolehippie.mdadm && \
    ansible-galaxy collection install openstack.cloud && \
    ansible-galaxy collection install azure.azcollection && \
    apk del gcc python3-dev libc-dev linux-headers wget && \
    rm get-pip.py

RUN scitq-manage ansible install

ENV FLASK_APP=scitq.server
ENV SQLALCHEMY_DATABASE_URI=sqlite:////var/lib/scitq/scitq.db
ENV DEBUG=1

VOLUME ["/var/lib/scitq" , "/root/.ssh", "/etc/ansible/inventory/02-scitq"]
ENTRYPOINT [ "flask", "run", "--host=0.0.0.0" ]

EXPOSE 5000

# docker run --rm -it miniscitq sh -c "FLASK_APP=scitq.server DEBUG=1 flask run"
