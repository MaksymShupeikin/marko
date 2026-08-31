# Keep the upstream entrypoint and database binaries, but apply current Alpine
# fixes and remove gosu. Compose runs the image as the postgres user, so the old
# privilege-drop helper is neither needed nor left in the runtime filesystem.
FROM postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73

RUN apk upgrade --no-cache \
    && rm -f /usr/local/bin/gosu

USER postgres
