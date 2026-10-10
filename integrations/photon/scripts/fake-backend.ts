/**
 * Throwaway stand-in for the Python backend's messaging endpoints (docs/API.md).
 * Every accepted inbound message enqueues an outbound reply to the sender, so a
 * single stdin line in mock mode exercises the full round trip.
 *
 *   PORT=8077 FAKE_FAIL_FIRST=1 npm run fake-backend
 *
 * FAKE_FAIL_FIRST=1 answers the first inbound POST with 503 to exercise retries.
 */
import http from "node:http";
import { randomUUID } from "node:crypto";

const PORT = Number(process.env.PORT ?? 8077);
const LEASE_MS = 60_000;
let failNextInbound = process.env.FAKE_FAIL_FIRST === "1";

interface Job {
  job_id: string;
  to_handle: string;
  conversation_id: string;
  text: string;
  leased_until: number;
  leased_by: string | null;
  result: unknown;
}

const seenEvents = new Set<string>();
const jobs = new Map<string, Job>();

function say(msg: string, data?: unknown) {
  console.log(`[fake-backend] ${msg}${data === undefined ? "" : " " + JSON.stringify(data)}`);
}

function send(res: http.ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readJson(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);

    if (req.method === "POST" && url.pathname === "/messages/inbound") {
      const body = await readJson(req);
      if (failNextInbound) {
        failNextInbound = false;
        say("inbound -> 503 (simulated failure)", { event_id: body.event_id });
        return send(res, 503, { detail: "simulated outage" });
      }
      const eventId = String(body.event_id ?? "");
      if (seenEvents.has(eventId)) {
        say("inbound duplicate", { event_id: eventId });
        return send(res, 200, { status: "duplicate" });
      }
      seenEvents.add(eventId);
      say("inbound accepted", body);
      const job: Job = {
        job_id: `job-${randomUUID().slice(0, 8)}`,
        to_handle: String(body.sender_handle),
        conversation_id: String(body.conversation_id),
        text: `Got it: "${String(body.text)}"`,
        leased_until: 0,
        leased_by: null,
        result: null,
      };
      jobs.set(job.job_id, job);
      say("enqueued outbound", { job_id: job.job_id, to_handle: job.to_handle });
      return send(res, 202, { status: "accepted" });
    }

    if (req.method === "POST" && url.pathname === "/messages/outbound/claim") {
      const body = await readJson(req);
      const max = Math.max(1, Math.min(50, Number(body.max ?? 10)));
      const now = Date.now();
      const claimed: Job[] = [];
      for (const job of jobs.values()) {
        if (claimed.length >= max) break;
        if (job.result === null && job.leased_until < now) {
          job.leased_until = now + LEASE_MS;
          job.leased_by = String(body.worker_id ?? "");
          claimed.push(job);
        }
      }
      if (claimed.length > 0) say("claimed", { worker_id: body.worker_id, job_ids: claimed.map((j) => j.job_id) });
      return send(res, 200, {
        jobs: claimed.map(({ job_id, to_handle, conversation_id, text }) => ({ job_id, to_handle, conversation_id, text })),
      });
    }

    const resultMatch = /^\/messages\/outbound\/([^/]+)\/result$/.exec(url.pathname);
    if (req.method === "POST" && resultMatch) {
      const jobId = decodeURIComponent(resultMatch[1]!);
      const job = jobs.get(jobId);
      if (!job) return send(res, 404, { detail: "unknown job" });
      const body = await readJson(req);
      job.result = body;
      say("result", { job_id: jobId, ...body });
      return send(res, 200, { status: "ok" });
    }

    if (req.method === "GET" && url.pathname === "/health") return send(res, 200, { status: "ok", fake: true });

    send(res, 404, { detail: "not found" });
  } catch (error) {
    send(res, 500, { detail: String(error) });
  }
});

server.listen(PORT, "127.0.0.1", () => say(`listening on http://127.0.0.1:${PORT}`));

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => server.close(() => process.exit(0)));
}
