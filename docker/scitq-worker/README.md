# Minimal usage

```bash
docker run --privileged --rm -d gmtscience/scitq-worker:latest
```

# Recommended usage

```bash
docker run -v /tmp:/scratch -v /tmp:/var/lib/docker -e NAME=node1  -e SCITQ_SERVER=$SCITQ_SERVER --privileged --rm -d gmtscience/scitq-worker:latest
```

# dind or dood ?

See https://shisho.dev/blog/posts/docker-in-docker/ for instance.

dind is recommended as it isolate worker dockers from general dockers in your setup, and it has been tested and validated.

dood does not work at this time. It *should* work also but it get stuck when `docker attach` instruction is launched within python code: FYI, the command used in dood mode should be (BUT THIS DOES NOT WORK):

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock --rm -it --entrypoint 'scitq-worker' scitq-worker:1.0b19 host.docker.internal 1
```