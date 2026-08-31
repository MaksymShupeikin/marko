# The upstream binary is statically linked. Copying that exact, signed-release
# image payload into scratch removes vulnerable unused Debian/OpenSSL libraries
# without rebuilding Cloudflare's security-sensitive tunnel client ourselves.
FROM cloudflare/cloudflared:latest@sha256:51c9cefcb4569df44e1ad403ab1d3d8065aa8e84339bcfc6aee75502e1140339 AS upstream

FROM scratch
LABEL org.opencontainers.image.source="https://github.com/cloudflare/cloudflared"
COPY --from=upstream /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=upstream /usr/local/bin/cloudflared /usr/local/bin/cloudflared
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/cloudflared", "--no-autoupdate"]
CMD ["version"]
