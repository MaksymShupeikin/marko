# syntax=docker/dockerfile:1
FROM ghcr.io/cirruslabs/flutter@sha256:46691e311715845de03a3ba4753a475476936805b29431b1f00f1816981033f8 AS build

WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get
COPY . .

ARG API_BASE_URL=http://localhost:8000
ARG PUBLIC_FIREBASE_API_KEY
ARG PUBLIC_FIREBASE_AUTH_DOMAIN
ARG PUBLIC_FIREBASE_PROJECT_ID
ARG PUBLIC_FIREBASE_MESSAGING_SENDER_ID
ARG PUBLIC_FIREBASE_WEB_APP_ID
ARG PUBLIC_GOOGLE_CLIENT_ID
RUN flutter build web --release \
    --csp \
    --no-web-resources-cdn \
    --pwa-strategy=none \
    --dart-define=API_BASE_URL=${API_BASE_URL} \
    --dart-define=FIREBASE_API_KEY=${PUBLIC_FIREBASE_API_KEY} \
    --dart-define=FIREBASE_AUTH_DOMAIN=${PUBLIC_FIREBASE_AUTH_DOMAIN} \
    --dart-define=FIREBASE_PROJECT_ID=${PUBLIC_FIREBASE_PROJECT_ID} \
    --dart-define=FIREBASE_MESSAGING_SENDER_ID=${PUBLIC_FIREBASE_MESSAGING_SENDER_ID} \
    --dart-define=FIREBASE_WEB_APP_ID=${PUBLIC_FIREBASE_WEB_APP_ID} \
    --dart-define=GOOGLE_CLIENT_ID=${PUBLIC_GOOGLE_CLIENT_ID} \
    && dart run tool/fingerprint_web.dart build/web \
    && dart run tool/verify_web_artifact.dart build/web

FROM nginxinc/nginx-unprivileged:alpine@sha256:d9083fe47768377ef55dedafd67d4da7c2f2bc2bece7554954f29359deb0dce9 AS runtime
USER root
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security_headers.conf /etc/nginx/security_headers.conf
COPY --from=build /app/build/web /usr/share/nginx/html
COPY web/flutter_service_worker.js /usr/share/nginx/html/flutter_service_worker.js
USER 101
EXPOSE 8080
