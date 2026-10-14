# Checkout Demo

A tiny checkout API for the Sentinel human-in-the-loop incident demo. It exposes real Prometheus metrics, has a clearly labeled fault switch, and keeps the repair as a reviewable GitHub pull request.

## Run locally

```powershell
docker compose up -d --build
```

Open <http://localhost:8000>. Click **Inject checkout fault**, then generate traffic:

```powershell
docker compose --profile load run --rm k6
```

Prometheus in the Sentinel stack scrapes `host.docker.internal:8000`. The alert fires from the app's measured checkout errors, not a constant demo expression. Stop traffic with `Ctrl+C`; turn off the fault from the app page or after Sentinel applies the approved configuration fix.

## GitHub repair loop

Sentinel creates a branch changing `app/settings.json` to disable the injected fault, opens a PR through GitHub's REST API, displays the actual PR diff and Actions checks, and waits for a human to approve and merge it in Sentinel. After merge, Sentinel syncs the merged settings file into this local demo app. It never edits or deploys an unrelated service.

GitHub Actions runs the small test suite for each PR. The app and its test data are synthetic and intended for localhost demo use only.

## Useful endpoints

- `GET /` — demo controls
- `POST /checkout` — order checkout API
- `GET /health` — health check
- `GET /metrics` — Prometheus metrics
- `POST /demo/fault` and `POST /demo/recover` — local demo fault controls
