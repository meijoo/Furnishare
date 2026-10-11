# Backend API and shared data contract

Every component (iPad, Photon adapter, Blender tools, ranker) builds against this file. The backend is the source of truth for households, proposals, approvals and financial operations.

- Base URL: `http://<mac-lan-ip>:8000` (dev: `http://127.0.0.1:8000`). Run with `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000` from `backend/`.
- Money: integer minor units (`*_cents`), currency `USD`.
- Lengths: meters. Canonical scene space is Y-up, origin at the floor center of the room, room width along X, room depth along Z, back wall at `z = -depth/2`. Rotation is `rotation_y_rad` about +Y.
- Timestamps: ISO 8601 UTC strings.
- Demo household id: `demo`. Demo member ids: `emily`, `maya`, `alex`.



## Product

```json
{
  "id": "ikea-kivik-3seat-tibbleby-beige-gray",
  "retailer": "IKEA",
  "retailer_product_id": "s09440580",
  "title": "KIVIK Sofa",
  "variant": "Tibbleby beige/gray",
  "category": "sofa",
  "description": "...",
  "image_url": "https://...",
  "local_image": "product_images/ikea-kivik.jpg",
  "source_url": "https://...",
  "price_cents": 59900,
  "currency": "USD",
  "dimensions_m": {"width": 2.28, "depth": 0.95, "height": 0.83},
  "dimension_kind": "assembled",
  "evidence": [{"field": "dimensions_m.width", "quote": "Width: 89 3/4\"", "source_url": "https://..."}],
  "retrieved_at": "2026-10-10T05:00:00Z",
  "additional_costs": {"shipping_cents": null, "tax_cents": null, "assembly_cents": null},
  "source_type": "verified",
  "style": {"color_hex": "#C9BFAE", "material": "fabric", "tags": ["light", "neutral"]},
  "asset_url": "/assets/<asset_key>.usdz"
}
```

- `category` is one of `sofa`, `coffee_table`, `tv`, `rug`.
- `dimensions_m` is `null` when assembled dimensions are not confirmed. Such products are never placed in the scale-aware layout. `dimension_kind` is `assembled`, `package` (not usable for layout) or `unknown`.
- Unknown additional costs are `null`, never `0`.
- `source_type`: `verified` (curated catalog, evidence checked), `live` (shopping search result), `demo` (fictional fixture).
- `asset_url` is `null` until a USDZ exists; clients draw a dimensioned placeholder box meanwhile.



## Scene object

```json
{
  "object_id": "obj-sofa",
  "product_id": "ikea-kivik-3seat-tibbleby-beige-gray",
  "category": "sofa",
  "position_m": [0.0, 0.0, -1.5],
  "rotation_y_rad": 0.0,
  "dimensions_m": {"width": 2.28, "depth": 0.95, "height": 0.83},
  "color_hex": "#C9BFAE",
  "asset_url": "/assets/ab12cd.usdz",
  "proposal_version": 3
}
```

`position_m` is the center of the footprint on the floor (y = 0 is the floor).

## Household state snapshot

`GET /households/{hid}/state` returns everything the iPad renders. Private contribution limits are never included except for the requesting member (`?member_id=`).

```json
{
  "household_id": "demo",
  "state_version": 42,
  "members": [{"id": "emily", "name": "Emily", "is_payer": true, "has_limit": true, "connected": true}],
  "catalog_mode": "verified",
  "room": {"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5,
           "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9}],
           "clearances": [{"label": "door swing", "x_m": 1.0, "z_m": 1.6, "width_m": 0.9, "depth_m": 0.9}],
           "inspiration_image_url": "/uploads/inspo.jpg"},
  "budget_cents": 150000,
  "proposal": {
    "version": 3, "status": "awaiting_approval",
    "items": [{"product_id": "...", "category": "sofa", "price_cents": 45000}],
    "known_total_cents": 45000,
    "unknown_costs": ["shipping", "tax"],
    "shares": {"emily": 17500, "maya": 17500, "alex": 10000},
    "approvals": {"emily": true, "maya": false, "alex": false},
    "objections": {"maya": "too dark"},
    "explanation": "Alex's limit is $100, so ...",
    "created_at": "..."
  },
  "scene": {"objects": [/* Scene object */], "validation": {"ok": true, "issues": []},
            "preview": {"url": "/uploads/previews/demo-v3-....png", "proposal_version": 3,
                        "validation": {"ok": true, "issues": []}}},  /* null until rendered */
  "finance": {
    "payer_id": "emily",
    "purchase": {/* Financial operation or null */},
    "reimbursements": [{"liability_id": "liab-maya-3", "from_member": "maya", "to_member": "emily",
                        "amount_cents": 17500, "operation": {/* or null */}}],
    "settled": false
  },
  "activity": [{"at": "...", "text": "Alex updated their limit"}]
}
```

Financial operation:

```json
{"op_key": "purchase:demo:v3", "kind": "purchase", "from_member": "emily", "to_member": null,
 "amount_cents": 45000, "proposal_version": 3,
 "state": "authorized|submitting|pending|confirmed|failed|unknown",
 "external_id": "5f...", "error": null, "updated_at": "...",
 "simulator": "mock|live"}
```

`simulator` says whether the operation ran against the in-process mock or the real Nessie sandbox. Neither moves real money. Retries after a failure get a new `op_key` with a `#n` suffix; `unknown` operations are only reconciled, never resubmitted.

Snapshot details:

- With `?member_id=`, that member's own entry also carries `limit_cents`; nobody else's limit is ever included.
- Proposal items also carry `title` and `source_type`.
- Validation issues are `{"kind", "objects": [object ids], "message"}`.
- An opening's `offset_m` is the center of the opening along its wall, in scene coordinates.
- `activity` is newest first. `/products` returns a bare array.
- Room bounds: width and depth 1.5–15 m, height 2–6 m.

Response bodies:

- Limit and object endpoints return `{"revised", "proposal_version", "message"}`.
- `PUT /room` returns the validation result.
- The inspiration upload returns `{"inspiration_image_url"}`.
- Chat returns `{"reply", "engine"}`, where `engine` is `gemini` or `deterministic`.

Proposal `status`: `draft`, `awaiting_approval`, `approved`, `superseded`, `purchased`, `settled`.

## Endpoints


| Method | Path                                                        | Purpose                                                                                                                                                                 |
| ------ | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/health`                                                   | Status and which integrations are configured                                                                                                                            |
| GET    | `/products?category=`                                       | Catalog                                                                                                                                                                 |
| GET    | `/households/{hid}/state?member_id=`                        | Snapshot above                                                                                                                                                          |
| GET    | `/households/{hid}/events`                                  | Server-sent events; each event `state` carries `{"state_version": n}`. Clients refetch state on change. Polling `/state` every 2 s is an acceptable fallback.           |
| PUT    | `/households/{hid}/room`                                    | Body: room object (without inspiration url)                                                                                                                             |
| POST   | `/households/{hid}/inspiration`                             | multipart `file` image upload                                                                                                                                           |
| POST   | `/households/{hid}/chat`                                    | `{"member_id", "text", "pick_ids", "mode": "design"|"refine", "skip_categories"}`; returns `{"reply"}`                                                                   |
| PUT    | `/households/{hid}/members/{mid}/limit`                     | `{"limit_cents"}` (private)                                                                                                                                             |
| POST   | `/households/{hid}/proposals/{version}/approve`             | `{"member_id"}`                                                                                                                                                         |
| POST   | `/households/{hid}/proposals/{version}/object`              | `{"member_id", "reason"}`                                                                                                                                               |
| PATCH  | `/households/{hid}/scene/objects/{object_id}`               | `{"position_m", "rotation_y_rad"}` persists a local move (optional)                                                                                                     |
| POST   | `/households/{hid}/purchase/authorize`                      | `{"member_id", "proposal_version"}` payer only                                                                                                                          |
| POST   | `/households/{hid}/reimbursements/{liability_id}/authorize` | `{"member_id"}` debtor only                                                                                                                                             |
| POST   | `/households/{hid}/finance/reconcile`                       | Re-query Nessie for pending/unknown ops                                                                                                                                 |
| POST   | `/households/{hid}/finance/setup`                           | Create Nessie customers, accounts and the merchant (done automatically on first operation)                                                                              |
| PUT    | `/households/{hid}/members/{mid}/handle`                    | `{"handle"}` maps a phone number or iMessage email to a member                                                                                                          |
| POST   | `/households/{hid}/scene/preview`                           | Rebuilds the current layout in Blender through the Blender MCP server and renders a PNG; returns `{"preview_url", "blender_validation"}`; 503 if Blender is unavailable |
| POST   | `/demo/reset?clear_handles=true`                            | Reseed the demo household with starter furniture; `clear_handles` also forgets registered handles                                                                       |
| POST   | `/demo/blank`                                               | Same members and plan as reset, but every room has no proposal or furniture (new-user start)                                                                            |
| GET    | `/debug/timings`                                            | Per-stage latency averages                                                                                                                                              |
| GET    | `/debug/outbound`                                           | Recent outbound message jobs                                                                                                                                            |
| GET    | `/uploads/{path}`                                           | Uploaded inspiration images and rendered previews                                                                                                                       |
| GET    | `/assets/{name}.usdz`                                       | Static assets                                                                                                                                                           |
| GET    | `/product_images/{file}`                                    | Static product images                                                                                                                                                   |




## Messaging (Photon adapter <-> backend)

The adapter owns the Photon connection; the backend owns decisions.

- `POST /messages/inbound` body `{"event_id", "sender_handle", "conversation_id", "text", "received_at"}`. Duplicate `event_id` returns `{"status": "duplicate"}`. Unknown handles get a registration prompt. Returns `202 {"status": "accepted"}`.
- `POST /messages/outbound/claim` body `{"worker_id", "max": 10}` returns `{"jobs": [{"job_id", "to_handle", "conversation_id", "text"}]}`. Claimed jobs are leased for 60 s.
- `POST /messages/outbound/{job_id}/result` body `{"status": "sent"|"failed", "provider_message_id", "error"}`.

Handles are E.164 phone numbers or iMessage email addresses, configured per member in `backend/data/members.json` (untracked) or via `PUT /households/{hid}/members/{mid}/handle`.

## Blender asset interface

`integrations/blender_mcp/assets.py` exposes, importable from the backend with no Blender in-process:

```python
def asset_key(product: dict, template_version: str = TEMPLATE_VERSION) -> str
def ensure_asset(product: dict, out_dir: Path) -> Path | None   # builds <asset_key>.usdz if missing; None on failure
```

Assets go in `backend/static/assets/`. The USDZ root sits on the floor (min y = 0), centered in X/Z, front facing +Z, in meters.

## Ranker interface

`ml/infer.py` exposes:

```python
class RankerService:
    @classmethod
    def load(cls, artifacts_dir: Path) -> "RankerService"   # never raises; falls back to cosine, then neutral
    mode: str                                              # "learned" | "cosine" | "neutral"
    def score(self, room_image: Path | None, product_ids: list[str]) -> dict[str, float]
```

Scores only compare products within one category.
## Apartment (multi-room)

The apartment is a floor plan that groups several **room scopes**. A room scope is an ordinary household (`/households/{hid}/...`, everything above applies unchanged) with its own members, budget, proposals, scene, approvals and payments.

- **Shared rooms** (living room, kitchen) have all roommates as members. Costs are split by `solve_split` with private limits, as before.
- **Private rooms** (bedrooms) have exactly one member, the owner. The owner pays 100%, approves alone, and has no reimbursements: once the purchase confirms, the room is settled.
- **Bathrooms and halls** have no room scope (`household_id: null`). They are drawn on the plan only.
- Texting (Photon) is bound to the living-room scope `demo`. Handles are globally unique, so members of other scopes have no handle and act through the app.

Demo ids: apartment `demo`; scopes `demo` (living room), `demo-bed-emily`, `demo-bed-maya`, `demo-bed-alex`. The kitchen is drawn but not furnishable yet (`household_id: null`, `kind: "kitchen"`).

Plan coordinates are meters, top-down: `x_m` grows to the right, `z_m` grows toward the front door, and the origin is the apartment's back-left corner. A room's own scene coordinates (Y-up, centered, back wall at `z = -depth/2`) map onto the plan with no rotation: plan `(x_m + width_m/2 + scene.x, z_m + depth_m/2 + scene.z)`.

`GET /apartments/{aid}`:

```json
{
  "id": "demo", "name": "3 bed / 3 bath apartment", "width_m": 10.5, "depth_m": 9.5,
  "members": [{"id": "emily", "name": "Emily"}, {"id": "maya", "name": "Maya"}, {"id": "alex", "name": "Alex"}],
  "rooms": [
    {"id": "living", "name": "Living room", "kind": "living", "shared": true, "owner_id": null,
     "household_id": "demo", "x_m": 0.0, "z_m": 5.5, "width_m": 4.5, "depth_m": 4.0,
     "summary": {"proposal_version": 2, "status": "awaiting_approval", "known_total_cents": 39900,
                 "shares": {"emily": 14950, "maya": 14950, "alex": 10000}, "item_count": 1,
                 "approvals_done": 1, "approvals_needed": 3, "settled": false}},
    {"id": "bed-emily", "name": "Emily's bedroom", "kind": "bedroom", "shared": false, "owner_id": "emily",
     "household_id": "demo-bed-emily", "x_m": 0.0, "z_m": 0.0, "width_m": 3.5, "depth_m": 3.5, "summary": {}},
    {"id": "bath-1", "name": "Bathroom", "kind": "bathroom", "shared": false, "owner_id": null,
     "household_id": null, "x_m": 0.0, "z_m": 3.5, "width_m": 2.5, "depth_m": 2.0, "summary": null}
  ],
  "totals": {"known_total_cents": 0, "by_member_cents": {"emily": 0, "maya": 0, "alex": 0}}
}
```

Rooms with a scope also carry `room_m` `{width_m, depth_m}`: the scope's actual 3D room. It can differ from the plan rectangle, after `PUT /households/{hid}/room` or a floor-plan import. To draw furniture inside the rectangle, scale scene coordinates by `width_m / room_m.width_m` and `depth_m / room_m.depth_m`.

`kind` is one of `living`, `kitchen`, `bedroom`, `bathroom`, `hall`. `summary` is `null` for rooms without a scope. `totals` sums the current proposal of every scope. `by_member_cents` is what each person pays across the whole apartment: their shared-room shares plus their own bedroom.

`POST /demo/reset` reseeds every scope of the demo apartment with starter furniture.
`POST /demo/blank` keeps the same plan and members but leaves every room empty.

### Bedroom categories

The catalog adds `bed`, `nightstand`, `dresser` and `desk`, using the same product schema as above. Bedroom scopes request `["bed", "nightstand", "dresser", "desk"]`.

Layout rules for bedrooms:
- The bed's headboard goes against the back wall, centered.
- One nightstand goes beside the bed on the side away from the door.
- The dresser goes against a side wall.
- The desk goes against the other side wall, or the back wall if there's room.
- Nothing may block the door swing.

Optional `style.shape`: `"rect"` (default) or `"round"`. Round products have `dimensions_m.width == depth` (the diameter). The Blender templates honor it, and the geometry checks keep using the bounding rectangle.

### Floor-plan import

`POST /apartments/{aid}/floorplan` (multipart: `file` = PNG or JPEG, optional `width_m` = overall plan width in metres, only needed when no room sizes are printed on the plan). It takes 10-30 s and needs Gemini; otherwise it returns `503`. It returns `422` when the plan can't be read or scaled and `415` for other image types.

Gemini reads each room's label, kind, printed size text and a rough box. The backend does the rest:
- It sets the scale from the printed sizes (median), using `width_m` only as a fallback.
- It trims overlapping boxes, such as a bedroom box that swallowed its closet.
- Uploaded bedrooms are named Bedroom 1, Bedroom 2, and so on in reading order (top-left first), with `owner_id: null`. All detected bedrooms remain on the plan; those under 2.4 m are drawn with a warning and get no scope. Furnishable unassigned bedrooms are accessible to all group members, including roommates who join later.
- It links the first living room to the live `demo` scope.
- It opens each numbered bedroom scope empty at the printed interior size, without assigning a user.

The living room's 3D room keeps its own geometry, so the live demo does not change. The `kind` values extend to `dining`, `closet`, `patio`, `laundry` and `other`.

Response: `{"apartment": <GET /apartments snapshot>, "warnings": [...], "seeded": {"bedroom-1": {"ok": true, ...}}, "scale_m_per_px": 0.0178}`.

After an import, `GET /apartments/{aid}` also returns:
- `"source": "imported"` (otherwise `"built_in"`).
- `image_url`: the uploaded plan.
- `image_frame_m` `{x_m, z_m, width_m, depth_m}`: where the whole image sits in plan coordinates, so clients can draw it under the rooms.
- `warnings`.
- Per room: optionally `label` (the text printed on the plan) and `interior_m` `{width_m, depth_m}` (the printed size, oriented to the plan).

`DELETE /apartments/{aid}/floorplan` restores the built-in plan and re-seeds the bedrooms. `POST /demo/reset` keeps whichever plan is current.

## Object textures

`POST /households/{hid}/scene/objects/{object_id}/texture` (multipart) is rugs only; other categories return 422:
- `file`: PNG or JPEG, at most 15 MB.
- Optional `mode`: `print` (the whole image across the rug; default) or `tile` (a repeating swatch).
- Optional `tile_m`: the tile size, 0.05-2.0 m.

The texture belongs to the object id, so it carries over when a revision swaps the product. A textured USDZ is built in the background. Scene objects with a texture gain:

```json
"texture": {"image_url": "/uploads/ab12.jpg", "mode": "print", "status": "building"}
```

`status` is one of:
- `building`: `asset_url` is still the plain model; the state version bumps when the build finishes.
- `ready`: `asset_url` points at the textured model.
- `failed`.
- `unavailable`: Blender is off.

`DELETE` on the same path removes the texture.

## Product search and realize

`GET /products/search?q=&limit=` uses SerpAPI Google Shopping when `SHOPPING_API_KEY` is set. Live listings with parsed or estimated `dimensions_m` are cached for design. Matching catalog items of the same type follow; a chair query will not return dressers.

`POST /products/realize` accepts a listing (`id`, `title`, `category`, `dimensions_m`, optional image/source URLs) and returns a generated USDZ plus form/dimension reads. `POST /products/realize/upload` is the same with a photo. `GET /products/realize/{id}` is the snapshot.

`PUT /households/{hid}/budget` `{ "budget_cents" }` updates the room budget.

Live search hits are cached so `catalog.get` and proposals can use `live-…` ids. A listing is usable in a design if it has placeable sizes (parsed or estimated).

## Design this room and refine

`POST /households/{hid}/chat` with `mode=design` fills a proposal from the prompt, optional `pick_ids` (Inspiration selections, preferred when they fit), inspiration photos, and `skip_categories` (owned items). Remaining categories come from catalog + live search.

If a proposal already exists, omit `mode` or send `mode=refine` to revise that proposal (“cheaper sofa”, “more oak”). “Start over” or `mode=design` publishes a new plan. The reply is `{"reply", "engine"}`; the 3D room updates on the next state/SSE tick.

## Roommate invitations and group preferences

`POST /households/{hid}/invitations`: `{ "members": [{"member_id", "phone"}], "request_id" }`.
Phones must be E.164 and members must belong to the room. Include the creator's phone.
At least two participants are required. Returns `{token, group_code, job_id, status}`. Codes are unique six-digit strings (including leading zeroes).
Each phone receives a separate DM containing the same code, compatible with shared
Photon lines. `PHOTON_ENABLE_GROUPS=0` is sufficient. Repeating a request id returns
the original invitation. `GET /invitations/{token}` returns aggregate delivery status
and `recipients: [{member_name, status, error}]`. Status is pending, sent, failed, or
partial (some sent, some failed); individual failures remain visible. Responses also
include `job_ids`, one job per phone, with `job_id` retained as the first job.
`POST /groups/join` accepts `{ "code": "123456" }` and returns `{household_id, group_name, group_code}`.
Unknown codes return 404; malformed codes return 422. The app validates the code
against the backend, then opens the matching room. Recipients must connect to the
same backend. Invitations predating codes require a new invitation; reset invalidates codes.

New invitation jobs are ordinary DM jobs with no group-creation payload. Replying
from a registered phone routes preferences and product URLs to that member’s room.
Existing dedicated-line group bindings remain supported; financial commands in
those groups still request a private message.

`GET /households/{hid}/suggestions` returns `{suggestions: [{id, member_name, text,
links, products}]}`. Text preferences accumulate across members, rank the verified
catalog, and optionally search shopping listings. Shared links are saved as references;
unverified listings never enter the scale-aware proposal automatically. State version
bumps notify the app to refresh its suggestions. This extends the existing demo room
membership; creating arbitrary new households/accounts remains outside this demo API.

## Persistent accounts and groups

Demo data stays in `seed.py`; it is independent of real accounts. SQLite in
`backend/data/app.db` now also stores users, sessions, groups, group memberships,
and room-to-group mappings. Signup never inserts a demo persona.

- `POST /auth/signup`: `{name,phone,username,password}` → `{token,user,groups}`.
  Username is case-insensitive and unique; phone is normalized and unique.
  Email is optional legacy profile data and does not have to be unique.
  Passwords have at least eight characters and are stored as salted scrypt hashes.
- `POST /auth/login`: `{username,password}` → the same response; invalid credentials → 401.
- `GET /auth/me`: bearer token → `{user,groups}`. Sessions expire after 30 days.
- `POST /auth/logout`: revokes the current bearer token.
- `POST /groups`: bearer token, `{name,location,request_id}` → group snapshot
  `{id,name,location,owner_id,group_code,household_id,members}`. Request id dedupes creation.
- `GET /groups`: lists the signed-in user's groups.
- `GET /groups/{id}`: group snapshot, membership required.
- `POST /groups/join`: `{code}` with a bearer token adds the signed-in user to a real
  group, idempotently, and returns `{household_id,group_name,group_code,group_id}`.
  Joining supersedes unpurchased proposals so new members participate in new proposals;
  joining while a purchase is in progress is rejected.

Real groups have an empty living-room household and a persisted apartment plan.
Their room APIs require group membership; member actions must use the signed-in
user's member id. Demo room APIs retain existing behavior. Phone numbers are account
profile data, not verified ownership; email/phone verification is not implemented.
Account sessions are saved in the iOS Keychain. Name/email display preferences remain
in UserDefaults. Account and group creation require a reachable backend.

Real-group invitations can include existing members or new `{phone,name}` invitees.
They send the group's existing code by DM. Invitees become members when they sign
up and join with that code; invitations do not create password-less accounts.

### Shared room design edits

`GET /households/{hid}/state` includes `design_edits: {epoch, edits}`. The edits
contain placed extra objects, products, option groups, owned items, chosen product
IDs, poses, visibility/removal sets, and dismissed suggestions.

`PATCH /households/{hid}/design-edits` accepts `{member_id, epoch, before, after}`.
The server applies the difference between the client's before/after snapshots,
preserving concurrent changes to other objects, groups, and options. Only members
of that room may edit it; real-group requests also require their authenticated
account. The room state version increments, causing connected devices to refresh.
Edits affect the scene and design estimate, not approved payment proposals.

A demo reset issues a new epoch and clears edits. Patches using an old epoch
return 409 so a reconnecting device cannot undo the reset. The iOS reset sends
`POST /demo/reset?clear_handles=true&furnished=true&full_reset=true` to restore the
furnished demo while clearing prior edits, photos, decisions, and demo messages.
