# Coordination

As of Oct 10, one session (bc-4d370c70) owns the whole repo again, including `backend/`. The earlier two-agent split is over.

Every component builds against `docs/API.md`:
- the iPad app (`ios/`)
- the Photon adapter (`integrations/photon/`)
- the Blender assets and MCP server (`integrations/blender_mcp/`)
- the ranker sidecar (`ml/serve.py` on 127.0.0.1:8100)

Change the contract there first.

Nessie findings, observed live (also in the `nessie.py` docstring):
- The base URL is `https://api.nessieisreal.com`; plain HTTP fails.
- Creating a purchase requires `merchant_id`, `medium` and `amount`.
- Creating a transfer requires `transaction_date`, `status`, `amount` and `description`.
- `GET /purchases/{id}` returns an API-gateway auth error, so reconcile by listing the account's purchases.
