# TLS certificates for the `web` service

By default, **`docker/web/entrypoint.sh`** generates a **self-signed** `server.crt` and `server.key` in this directory the first time the container starts (when the files are missing).

## Use your own certificate

Before `docker compose up`, place PEM files here:

- **`server.crt`** — leaf certificate (optionally with chain concatenated per your CA’s instructions)
- **`server.key`** — private key (readable only by the container user; avoid committing this directory’s keys to git)

Then start Compose as usual; the entrypoint skips generation when both files exist.

For **browser trust**, import your CA or use a certificate from your organization’s PKI. Self-signed certificates will show a browser warning until trusted or replaced.
