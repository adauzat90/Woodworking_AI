# Convex backend — saved designs

Optional cloud persistence for the cabinet designer. Without it, the web app
saves designs to the browser's `localStorage` (works offline, per-browser).

## Connect a Convex deployment

```bash
npm install                 # installs the convex client
npx convex dev              # logs in, provisions a dev deployment, writes
                            # convex/_generated/ and a CONVEX_URL to .env.local
```

Then start the Python web app with that URL exposed to the front end:

```bash
export CONVEX_URL="https://<your-deployment>.convex.cloud"
python -m woodworking_ai.web
```

The page reads `CONVEX_URL` (injected by the backend) and, when present, stores
designs in Convex instead of `localStorage` — so they're shared across browsers
and devices in real time.

## Functions

| Function | Kind | Purpose |
|---|---|---|
| `designs:save`   | mutation | insert `{name, spec}` |
| `designs:list`   | query    | 50 most recent designs |
| `designs:get`    | query    | one design by id |
| `designs:remove` | mutation | delete by id |

`spec` is stored opaquely (`v.any()`) — it's the furniture-DSL JSON the Python
engine produces, so the schema never has to track the DSL's evolution.
