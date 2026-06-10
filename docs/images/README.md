# README screenshots

PNG captures for the root [`README.md`](../README.md) feature tour. Taken from a running Docker Compose stack (dark theme, 1280×800 viewport).

| File | Route | Description |
|------|-------|-------------|
| `login.png` | `/auth/login` | Sign-in page |
| `home-map.png` | `/` | Home dashboard and fleet map |
| `devices-grid.png` | `/devices` | Inventory grid with cellular sparklines |
| `device-detail.png` | `/devices/{id}` | Device detail and live-data controls |
| `cellular-history.png` | `/devices/{id}` (scrolled) | EIOLTE RF history chart |
| `sdwan-admin.png` | `/administration/sd-wan` | Register and verify Managers |

## Re-capture

With the stack up (`docker compose up -d` or `./scripts/launch-terra-debug.sh`):

```bash
TERRA_SCREENSHOT_BASE_URL=https://localhost:4434 \
TERRA_ADMIN_EMAIL=admin@terra.local \
TERRA_ADMIN_PASSWORD='ChangeMe!Admin-1st-login' \
node scripts/capture-readme-screenshots.mjs
```

Requires Playwright Chromium (`npx playwright install chromium` once). Device **10** is used for detail/history shots when present in inventory.
