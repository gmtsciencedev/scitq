# minimal (with sqlite)

DO NOT USE IN PRODUCTION

```bash
docker run -d -p 5000:5000 gmtcience/scitq-server:latest
```

You can mount also a file in `/etc/ansible/inventory/02-scitq to provide different options for ansible worker deploy code.

# with postgresql

```bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_DB=scitq -p 55000:5432 -d postgres
```

```bash
docker run -d -p 5000:5000 -e SQLALCHEMY_DATABASE_URI=postgresql://postgres:mysecretpassword@host.docker.internal:55000/scitq gmtcience/scitq-server:latest
```

Same as above, you can mount also a file in `/etc/ansible/inventory/02-scitq to provide different options for ansible worker deploy code.

Note that this is not really production ready: a production setup needs postgresql AND uwsgi which is not available (yet) in this docker. This still use the debug server mode, which is simpler but will not perform well even under moderate load.

## On macos with Apple M1/M2

```bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_DB=scitq -p 55000:5432 -d postgres
docker run -d -p 127.0.0.1:5000:5000 -e SQLALCHEMY_DATABASE_URI=postgresql://postgres:mysecretpassword@host.docker.internal:55000/scitq gmtcience/scitq-server:arm64-latest
``````