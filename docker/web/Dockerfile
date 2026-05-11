# syntax=docker/dockerfile:1
# Multi-arch TLS edge (amd64 + arm64).
FROM nginx:1.27-alpine

RUN apk add --no-cache openssl curl

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fk https://127.0.0.1/health >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
