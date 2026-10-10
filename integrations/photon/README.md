# Photon iMessage adapter

A small Node/TypeScript service that connects iMessage, through Photon's Spectrum SDK, to the RAG to Rooms backend. It owns only the Photon connection; the backend makes every decision. The HTTP contract it follows is the "Messaging (Photon adapter <-> backend)" section of [`docs/API.md`](../../docs/API.md).

- **Inbound:** each iMessage from someone other than the agent is POSTed to `/messages/inbound`.
- **Outbound:** about once a second it calls `/messages/outbound/claim`, sends each job as a 1:1 iMessage to `to_handle`, then reports the outcome to `/messages/outbound/{job_id}/result`.

## Setup

Requires Node 22 or newer (developed on Node 25).

```bash
cd integrations/photon
npm install
```

Credentials go in the **repo-root** `.env`, which is gitignored:

```bash
PHOTON_PROJECT_ID=...        # Spectrum Cloud project, from https://app.photon.codes
PHOTON_PROJECT_SECRET=...
BACKEND_URL=http://127.0.0.1:8000
```

The optional settings (worker id, poll interval, self handles, groups, log level) are documented in [`.env.example`](./.env.example). You can also put them in `integrations/photon/.env`. That file is loaded after the root `.env` and never overrides it.

## Run

| Command | What it does |
| --- | --- |
| `npm start` | Real mode: connects to Photon and the backend |
| `npm run mock` | No Photon: stdin lines become inbound messages, outbound jobs print to stdout |
| `npm run fake-backend` | A throwaway implementation of the 3 messaging endpoints on port 8077 |
| `npm run typecheck` (or `build`) | `tsc --noEmit` |

### Test without credentials

Use two terminals:

```bash
# terminal 1: fake backend that replies "Got it: ..." to every inbound message
npm run fake-backend                       # FAKE_FAIL_FIRST=1 makes the first inbound return 503

# terminal 2
BACKEND_URL=http://127.0.0.1:8077 npm run mock
+15551234567: my limit for the sofa is $100
```

Terminal 2 prints `[outbound job-…] -> +15551234567: Got it: "my limit for the sofa is $100"`. To exercise the real flow, start the Python backend on port 8000 instead and run `npm run mock`.

Logs are JSON lines on **stderr**, which keeps stdout clean in mock mode. Logs never contain secrets or message bodies. They include only `text_length`, and handles are masked (`+1555***4567`).

## Behavior details

- **Self messages.** The SDK's iMessage provider already drops events with `isFromMe`. As a second layer, the adapter also skips messages where any of these is true:
  - `message.direction === "outbound"`
  - `sender.kind === "agent"`
  - the sender equals the receiving line's own number (`space.phone`, on dedicated lines)
  - the sender is listed in `PHOTON_SELF_HANDLES`
- **Inbound fields.** `event_id` is the Spectrum `message.id`, which is the Apple message GUID. `conversation_id` is the Spectrum `space.id`, which is the chat GUID (for example `any;-;+15551234567` for a DM). `sender_handle` is `message.sender.id`, the E.164 number or email exactly as Apple reports it. `received_at` is `message.timestamp`.
- **Non-text messages** (attachments, reactions, polls, and so on) are logged and skipped. Multi-part messages have their text parts joined with newlines.
- **Inbound dedupe and retry.** A 2000-entry in-memory LRU of event ids drops redeliveries. The POST retries with exponential backoff and jitter on network errors, 5xx and 429, up to 8 attempts. That is safe because the backend dedupes durably by `event_id`. If every attempt fails, the message is dropped and logged, and its id is removed from the LRU so a redelivery can try again.
- **Outbound at-most-once per process.** Every claimed `job_id` is recorded before sending. If the backend hands back a job this process already attempted, for example because the result POST was lost and the 60 s lease expired, the adapter re-reports the stored result and does not send again. A failed result POST is retried with backoff, then again on each later tick, and once more at shutdown.
- **Choosing the outbound line.** On dedicated lines, a DM reply goes out from the line that last heard from that handle, using `space.create(handle, { phone })`. Otherwise the SDK picks a line.
- **Groups** are off by default (`PHOTON_ENABLE_GROUPS=0`). In that mode, inbound group messages are skipped and every job goes out as a DM to `to_handle`. With groups on, inbound group messages are forwarded, and a job whose `conversation_id` is a group chat GUID (`;+;`) is sent into that chat via `space.get(conversation_id)`. The SDK supports this only on **dedicated** lines. Shared (pooled) lines are DM-only, and the adapter logs a warning when it detects that combination.
- **Shutdown.** SIGINT or SIGTERM stops claiming new jobs and lets the job currently sending finish. Jobs that were claimed but not started are left to expire their lease. The adapter then flushes unreported results, calls `app.stop()` and exits. If shutdown takes longer than 15 s, the process is forced to exit.
- **Unexpected stream end.** If the Photon inbound stream ends on its own, the process exits with code 1 so a supervisor can restart it.

## SDK usage

The adapter uses `spectrum-ts@12.10.1`, pinned exactly because the SDK releases often. It is the batteries-included package, which pulls in `@spectrum-ts/core` and `@spectrum-ts/imessage@12.10.1`. Every call below was checked against the installed type definitions and provider source in `node_modules`, and against the official `examples/basic` in [photon-hq/spectrum-ts](https://github.com/photon-hq/spectrum-ts).

| Purpose | Call |
| --- | --- |
| Connect | `Spectrum({ projectId, projectSecret, providers: [imessage.config()] })` from `spectrum-ts` and `spectrum-ts/providers/imessage` |
| Receive | `for await (const [space, message] of imessage(app).messages)`; read `message.content.type === "text"` and `message.content.text` |
| Identify self | The provider's built-in `isFromMe` filter, plus `message.direction`, `message.sender.kind === "agent"` and `space.phone` (the receiving line's number; `"shared"` on pooled lines) |
| Find or create a DM | `imessage(app).space.create(handle)` or `space.create(handle, { phone })`. On shared lines this resolves locally to `any;-;<handle>`; on dedicated lines it calls `chats.create` |
| Existing group | `imessage(app).space.get(chatGuid, { phone? })` |
| Send | `space.send(text(body))`, which resolves to a `Message` whose `.id` becomes `provider_message_id` |
| Shut down | `app.stop()` (Spectrum installs no signal handlers itself) |

### Not verified

These could not be checked without real credentials:

- **No live iMessage traffic has been tested.** Only mock mode and the credential-rejection path ("Invalid credentials") were exercised.
- **Whether `space.send` always returns a message id** for iMessage text sends. The adapter reports `provider_message_id: null` if it returns `undefined`.
- **Whether the stream replays missed messages after a restart.** The SDK tracks cursors internally, but they appear to be in memory only, so messages that arrive while the adapter is down may be lost.
- **Whether `message.id` is unique per message.** For multi-part messages the provider can emit part ids like `p:N/<guid>`. The adapter does not enable `flattenGroups`, so a multi-part message should arrive as one `group` message with one id, but this was not observed live.
- **Shared vs dedicated line detection.** `cloud.getImessageInfo(projectId)` exists but returned "Missing authorization header" when called with just a project id, so the adapter instead infers the line type from the first inbound message.
- **Group behavior on a shared line**, and whether the account tier allows groups at all.
- **Sending to email handles.** The SDK accepts them, and `space.create` takes "E.164 phone or email", but they were not tested live.

The SDK reads a few environment variables of its own. They are optional and normally left unset: `LOG_LEVEL` (shared with this adapter), `SPECTRUM_CLOUD_URL`, `SPECTRUM_IMESSAGE_ADDRESS` and `DEPLOYMENT_ENV`. Telemetry is off unless `Spectrum({ telemetry: true })` is passed, and this adapter does not pass it.

## Files

- `src/index.ts`: wiring, signals, shutdown
- `src/config.ts`: dotenv loading (repo-root `.env`) and environment parsing
- `src/photon.ts`: the Spectrum transport (receive, self filter, send)
- `src/mock.ts`: the stdin/stdout transport
- `src/inbound.ts`: LRU dedupe and forwarding
- `src/outbound.ts`: the claim/send/result loop
- `src/backend.ts`: the HTTP client with retry
- `scripts/fake-backend.ts`: the fake implementation of the three endpoints
