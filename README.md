# RAG to Rooms

Roommates furnish a shared living room together. An AI agent proposes real products that fit the room, the budget and each person's private contribution limit. Everyone approves by text or on the iPad. The payer buys through the Nessie sandbox (fake money), the others reimburse, and the iPad shows the layout in 3D and in AR at true scale.

## Components

| Folder | What it is | Needs |
|---|---|---|
| `backend/` | FastAPI + SQLite: proposals, split solver, layout checks, payments queue, messaging, Gemini agent | Python 3.13 (3.10+), any OS |
| `ios/` | SwiftUI + RealityKit iPad/iPhone app: 3D room, AR, panels | Mac with Xcode 26 |
| `integrations/photon/` | iMessage adapter (Photon Spectrum) | Node 22+ |
| `integrations/blender/`, `integrations/blender_mcp/` | Furniture templates, USDZ asset builds, Blender MCP server | Blender 5.x |
| `ml/` | SigLIP2 image ranker sidecar, labeling page, training and evaluation | Python 3.13, separate venv |
| `docs/` | `API.md` is the contract between all parts. Change it first. | |

## Setup

```sh
git clone <repo-url> && cd rag-to-rooms
cp .env.example .env            # keys are optional; see below

# Backend (and Blender MCP server), using the repo-root venv
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# Ranker (optional; the backend falls back without it)
python3.13 -m venv ml/.venv
ml/.venv/bin/pip install -r ml/requirements.txt

# Photon adapter (optional)
cd integrations/photon && npm install && cd ../..
```

macOS's built-in `python3` is 3.9, which is too old. Install Python 3.13 with `brew install python@3.13`.

### Keys (`.env`, never committed)

Everything runs **without keys** using clearly labeled fallbacks:

| Key | Without it |
|---|---|
| `NESSIE_API_KEY` | Payments run in an in-process mock, labeled "Simulated (mock)" |
| `GEMINI_API_KEY`, or Vertex (`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_MODEL`) | A deterministic planner replaces the agent |
| `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET` | Use `npm run mock` to type messages in a terminal |
| `SHOPPING_API_KEY` (SerpAPI) | Verified catalog only |

Ask the team lead for keys privately. Never paste them into the repo, issues or chat logs.

## Run

```sh
cd ml && .venv/bin/python serve.py             # terminal 1: ranker on 127.0.0.1:8100 (optional)
backend/scripts/serve.sh                       # terminal 2: backend on 0.0.0.0:8000
```

- **Health:** http://localhost:8000/health shows which integrations are live.
- **iPad app:** open `ios/RagToRooms.xcodeproj`, pick your Team under Signing & Capabilities, and run on a device. Then open the gear icon and type the Mac's IP (`ipconfig getifaddr en0`); the app adds `http://` and `:8000`. The iPad must be on the same Wi-Fi. Campus and guest Wi-Fi usually block device-to-device traffic: use a phone hotspot, or run `backend/scripts/tunnel.sh`. It prints a `https://….trycloudflare.com` URL and shows a QR code; scan the code with the iPad Camera app to connect without typing. `cd backend && ../.venv/bin/python scripts/connect_qr.py` shows the same kind of code for the Mac's Wi-Fi IP. With the iPad on a cable, `xcrun devicectl device process launch --device <id> com.emilyjon.ragtorooms -backendBaseURL <url>` also sets it. See `ios/README.md`.
- **Whole demo without a phone:** `cd backend && ../.venv/bin/python scripts/demo_run.py` sends fake texts and prints every reply.
- **Typed texts:** `cd integrations/photon && npm run mock`, then type `+15550000003: my limit is $100`.
- **Labeling page:** `cd ml && .venv/bin/python label/server.py` opens on port 8200. Add `--host 0.0.0.0` so teammates can label from their own devices.
- **Reset the demo:** use the app's Settings → Reset demo, or `curl -X POST 'localhost:8000/demo/reset?clear_handles=true'`.

## Tests

```sh
cd backend && ../.venv/bin/python -m pytest -q                      # 42 tests, no keys or network needed
cd integrations/blender_mcp && ../../.venv/bin/python -m pytest -q  # 166 tests (needs Blender for some)
cd ml && .venv/bin/python -m pytest -q                              # 25 tests
cd integrations/photon && npm run typecheck
```

Run the tests for the area you touched before opening a pull request.

## Team workflow

- Work on a branch, e.g. `git checkout -b blender/round-table`, and open a pull request into `main`.
- Stay inside your own folder where possible (see the table above). Changes to how parts talk to each other go in `docs/API.md` first.
- Never commit `.env`, `backend/data/members.json` (real phone numbers), databases or model weights. `.gitignore` covers them.

## Safety rules the code enforces

- The AI only proposes. Approvals, payments and settlement are fixed backend code.
- Every change creates a new proposal version, and approvals of older versions are rejected.
- Private limits are never shown or texted to other roommates.
- Money moves only after an explicit PAY or SEND from the right person. An uncertain payment is checked with Nessie, never blindly retried.
- Nessie is a sandbox: no real money moves.

## Accounts and saved groups

**Create your account** now saves a real user in `backend/data/app.db`. Log in with
that email/password to return to your saved groups. **Group setup** creates a
persistent group, with an empty living room and a six-digit join code. **Join a
group** validates the code and stores membership for the signed-in account.
Passwords are salted scrypt hashes; session tokens are hashed in SQLite, expire
after 30 days, and are stored in the iOS Keychain. Phone/email verification is not
yet implemented. Account and group creation require the backend to be running.

Use **Try demo** on the welcome screen for Emily, Maya, and Alex. Demo resets
preserve real users, groups, memberships, and their invitation jobs. Set
`RTR_SEED_DEMO=0` to disable automatic demo seeding on backend startup; existing
demo records remain until explicitly reset or removed. The default is `1`.

To inspect saved records without passwords or session tokens:

```sh
sqlite3 backend/data/app.db "SELECT id, name FROM users;"
sqlite3 backend/data/app.db "SELECT id, name, location FROM groups;"
sqlite3 backend/data/app.db "SELECT group_id, user_id, role FROM group_members;"
```

New group members join as themselves, rather than taking a demo persona's seat.
Share lets you enter new roommates' phone numbers and sends the group's code in
individual Photon messages. Recipients still need Photon permission to receive
messages on your shared line. Text preferences target the most recently created
or joined group for that phone. Floor-plan imports are saved per real group;
bedroom scopes use the group's real member ids.
