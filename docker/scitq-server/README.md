# minimal (with sqlite)

DO NOT USE IN PRODUCTION

```bash
docker run -d --rm -p 5000:5000 -v /tmp:/var/lib/scitq scitq-server:1.0b19
```

# with postgresql

```bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_DB=scitq -p 55000:5432 -d postgres
```

```bash
docker run -d --rm -p 5000:5000 -e SQLALCHEMY_DATABASE_URI=postgresql://postgres:mysecretpassword@host.docker.internal:55000/scitq scitq-server:1.0b19
```
