#!/bin/sh
set -e
CERT=/etc/nginx/certs/server.crt
KEY=/etc/nginx/certs/server.key
if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
    echo "terra-web: generating self-signed TLS material (replace with your own server.crt + server.key in docker/certs/)"
    mkdir -p /etc/nginx/certs
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
        -keyout "$KEY" \
        -out "$CERT" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1"
    chmod 644 "$CERT"
    chmod 600 "$KEY"
fi
exec nginx -g "daemon off;"
