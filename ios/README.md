# RAG to Rooms: iPad client

Native SwiftUI + RealityKit app for the shared-apartment demo. It renders the household state from the backend (`docs/API.md`): an apartment floor plan, proposal, contributions, simulated payments, activity, and a true-scale 3D room you can edit locally or place in AR.

Requirements: Xcode 16 or newer (built with Xcode 26.6), iPadOS 17+. No third-party packages.

## Layout

```
RagToRooms/
  App/          RagToRoomsApp (injects the @Observable AppModel)
  Models/       Codable wire types (tolerant decoding), procedural placeholder parts
  Networking/   BackendClient (URLSession async/await), EventStream (SSE parser)
  Store/        AppModel (connection loop, local edits, actions), OfflineDemo (fixture simulation)
  Scene/        RoomRealityView (non-AR 3D room), EntityFactory/FurnitureNode, AssetCache (USDZ on disk), LayoutValidation
  AR/           ARPlacementScreen (two-tap room alignment + single item), RoomAlignment math, RoomPlan capture
  Views/        Panels, sheets and the Frutiger Aero theme
  Resources/    demo_state.json, demo_products.json, demo_apartment.json (offline demo fixtures)
```

The Xcode project uses a file-system synchronized group, so new files under `RagToRooms/` are picked up automatically. `Info.plist` is excluded from the bundle resources via a membership exception.

## Run in the Simulator

1. Start the backend (from `backend/`): `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. Open `ios/RagToRooms.xcodeproj`, choose an iPad simulator, and run. The default backend URL is `http://127.0.0.1:8000`, which the Simulator can reach on the Mac.

Command line:

```sh
xcodebuild -project ios/RagToRooms.xcodeproj -scheme RagToRooms \
  -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M5)' -derivedDataPath /tmp/rtr-dd build
xcrun simctl install booted /tmp/rtr-dd/Build/Products/Debug-iphonesimulator/RagToRooms.app
xcrun simctl launch booted com.emilyjon.ragtorooms
```

DEBUG builds accept launch arguments that help with screenshots: `-RTRScrollTo floorplan|proposal|contributions|finance|product|chat|activity`, `-RTRSelect obj-sofa`, `-RTRSwitchTo bed-emily` (switches room at runtime, like tapping the plan), and `-backendBaseURL http://host:port`. Any `UserDefaults` key can be overridden this way, e.g. `-currentHouseholdID demo-bed-emily` or `-actingMemberID maya`.

## Run on a physical iPad

1. **Signing:** select the RagToRooms target → Signing & Capabilities → choose your Team (a free personal team works). If the bundle id `com.emilyjon.ragtorooms` is taken, change it to something unique.
2. **Backend on the LAN:** run uvicorn with `--host 0.0.0.0` (not `127.0.0.1`) so other devices can connect. Allow incoming connections if macOS asks.
3. **Find the Mac's IP:** System Settings → Wi‑Fi → Details → IP address (or `ipconfig getifaddr en0`). The iPad and Mac must be on the same network; guest or captive Wi‑Fi often blocks device-to-device traffic.
4. Run the app on the iPad, tap the gear → **Backend**, enter `http://<mac-ip>:8000`, tap **Connect**. **Check /health** confirms reachability. Allow the Local Network prompt on first launch.
5. **AR:** tap **View in AR**, allow the camera, and wait for the coaching overlay to find the floor. In **Whole room** mode, stand facing the room's back wall and tap the floor at the back-left corner, then tap a second floor point further right along the back wall. The whole layout is placed relative to those two points at true scale. **Single item** mode drops the chosen piece wherever you tap, facing you. Drag to move and twist with two fingers to rotate. **Reset** restarts tracking.

### Why App Transport Security allows arbitrary loads

The backend is plain HTTP on a LAN IP such as `http://192.168.1.20:8000`. `NSAllowsLocalNetworking` covers `.local` hostnames and unqualified names, but it does not reliably cover raw IP addresses (campus networks often hand out public ones). So `Info.plist` sets only `NSAllowsArbitraryLoads`. Do not add `NSAllowsLocalNetworking` back: when it is present, iOS ignores `NSAllowsArbitraryLoads`, and IP connections fail with "Blocked by App Transport Security". This is acceptable for a hackathon demo talking to a local backend. Remove it (or switch to HTTPS) before shipping anything real. `NSLocalNetworkUsageDescription` is required for the iOS local-network permission prompt.

## Behavior notes

- **Apartment and room scopes:** the *Apartment* panel (top of the panels column, collapsible) draws `GET /apartments/demo` to scale. Tapping a living room or bedroom, or a chip in the top bar (*Living room · Emily's room · Michelle's room · Annabel's room*), calls `AppModel.selectRoom`. That switches `currentHouseholdID`, points `BackendClient.householdID` at the room's scope (`demo`, `demo-bed-emily`, …), restarts the SSE/polling loop and refetches state, so the 3D room, proposal, contributions, finance, chat and AR all show that room. Each scope's last snapshot is kept, so switching back is instant. Bathrooms, halls and the kitchen (no `household_id`) are drawn muted and can't be tapped. The current room's furniture footprints are drawn inside its rectangle. The plan refreshes on every state change and every 5 s while it is on screen. If `/apartments/demo` 404s, the bundled `demo_apartment.json` plan is used (badge *Bundled plan*), with each room's summary rebuilt from that scope's live `/state`. If a bedroom scope itself 404s, its fixture is shown with a notice and actions stay local. In a bedroom, the owner pays 100%, approves alone and has no limit or reimbursements. Acting as anyone else shows "Only Emily approves this bedroom" (with an *Act as Emily* shortcut) instead of buttons that would 4xx.
- **Sync:** the app opens `GET /households/{current scope}/events` (SSE) and refetches `/state` whenever a `state` event's `state_version` differs from what it has. If the stream fails, it polls `/state` every 2 s for about 30 s, then tries SSE again. The badge in the top bar shows *Live (events)*, *Live (polling 2 s)*, *Connecting…* or *Offline*.
- **Offline demo:** if the backend has never been reached, the app runs from bundled fixtures with a local simulation of approvals and simulated payments. It's labeled *Offline demo* / *Demo fixtures*. Once a backend has been reached, losing it keeps the last known state and shows *Offline: last known state*.
- **Local editing:** tap selects, drag moves on the floor, two-finger twist or the ↺/↻ buttons rotate. All of this is local. Settings → *Save moves to the backend* additionally sends `PATCH /scene/objects/{id}` at the end of each gesture. Local hints (outside the room, overlap with other non-rug footprints, blocked clearance zones) use oriented-rectangle (separating axis) checks that mirror `backend/app/geometry.py`.
- **3D assets:** when `asset_url` is set, the USDZ is downloaded once into `Caches/USDZ` and swapped in with a short scale animation. Until then, or if loading fails, a procedural placeholder with the exact outer dimensions is shown. Updates are diffed by `object_id`; only entities whose product, dimensions, color or asset changed are rebuilt.
- **Previews:** in the product panel, *Preview* swaps a selected object for a same-category alternative locally. It is labeled *Preview (local only)* and is never sent to the server.
- **Financial states** are always shown as text plus an SF Symbol. Color is never the only cue. *Simulated (mock)* appears whenever the backend reports `simulator: "mock"`.

## What's verified vs needs a device

Verified (Xcode 26.6, 2026‑10‑10):
- `xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` succeeds with no Swift warnings.
- Simulator build, install and launch on iPad Pro 11" and 13" (M5) simulators against the running backend. Live state decodes (proposal v2, 4 scene objects), SSE connects (*Live (events)*), product photos load from `/product_images/`, and Blender USDZ assets download into the cache and render in the room view.
- Portrait layout, the landscape split (room left, panels right), and every panel: proposal, contributions, finance (settled banner, mock badges), product evidence with alternatives, chat box, activity.
- Offline demo fallback when the backend URL is unreachable.
- Apartment plan (portrait, 13" M5): live living room plus live bedroom scopes with the bundled plan while `/apartments/demo` 404s; runtime switch into Emily's bedroom (`-RTRSwitchTo`); the read-only note when acting as Michelle there; fully offline bedroom fixture with footprints. Not yet checked: the landscape split with the plan, and a live `/apartments/demo` response.
- Apartment plan (portrait, 13" M5): live living room plus live bedroom scopes with the bundled plan while `/apartments/demo` 404s; runtime switch into Emily's bedroom (`-RTRSwitchTo`); the read-only note when acting as Michelle there; fully offline bedroom fixture with footprints. Not yet checked: the landscape split with the plan, and a live `/apartments/demo` response.

Needs a physical iPad:
- The AR screen: world tracking, the coaching overlay, the two-tap alignment accuracy, per-object gestures, and the camera permission flow. The Simulator has no world tracking, so it shows an explanatory screen instead.
- RoomPlan capture (only offered on LiDAR devices where `RoomCaptureSession.isSupported`).
- LAN connectivity with a real IP, the Local Network permission prompt, and the ATS behavior.
- PhotosPicker inspiration upload end to end, chat round-trips with the live agent, and the approve/object/limit/authorize buttons against the backend (all wired to the documented endpoints, but not tapped through in this session).
