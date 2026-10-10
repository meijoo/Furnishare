import { errorMessage, log } from "./log.ts";

export interface InboundEvent {
  event_id: string;
  sender_handle: string;
  conversation_id: string;
  text: string;
  received_at: string;
}

export interface OutboundJob {
  job_id: string;
  to_handle: string;
  conversation_id: string | null;
  text: string;
  participants?: string[];
  invitation_token?: string;
  line_phone?: string | null;
}

export interface JobResult {
  conversation_id?: string;
  line_phone?: string;
  status: "sent" | "failed";
  provider_message_id: string | null;
  error: string | null;
}

/** HTTP error from the backend. 4xx is not retried; 5xx is. */
export class BackendHttpError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    body: string,
  ) {
    super(`backend ${path} returned HTTP ${status}: ${body.slice(0, 200)}`);
  }
}

const REQUEST_TIMEOUT_MS = 10_000;

function isRetryable(error: unknown): boolean {
  if (error instanceof BackendHttpError) return error.status >= 500 || error.status === 429;
  return true;
}

export const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal?.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });

export interface RetryOptions {
  attempts: number;
  baseMs: number;
  maxMs: number;
  signal?: AbortSignal;
}

export class BackendClient {
  constructor(private readonly baseUrl: string) {}

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    const text = await res.text();
    if (!res.ok) throw new BackendHttpError(res.status, path, text);
    return (text ? JSON.parse(text) : {}) as T;
  }

  /**
   * Exponential backoff with jitter on network errors / 5xx / 429.
   * Only used for calls that are idempotent on the backend side.
   */
  private async postWithRetry<T>(path: string, body: unknown, opts: RetryOptions): Promise<T> {
    let attempt = 0;
    for (;;) {
      attempt += 1;
      try {
        return await this.post<T>(path, body);
      } catch (error) {
        if (!isRetryable(error) || attempt >= opts.attempts || opts.signal?.aborted) throw error;
        const delay = Math.min(opts.maxMs, opts.baseMs * 2 ** (attempt - 1)) * (0.5 + Math.random() / 2);
        log.warn("backend request failed, retrying", {
          path,
          attempt,
          retry_in_ms: Math.round(delay),
          error: errorMessage(error),
        });
        await sleep(delay, opts.signal);
      }
    }
  }

  /** Safe to retry: the backend dedupes durably by event_id. */
  postInbound(event: InboundEvent, signal?: AbortSignal): Promise<{ status: string }> {
    return this.postWithRetry("/messages/inbound", event, { attempts: 8, baseMs: 500, maxMs: 15_000, signal });
  }

  /** Not retried here: the caller's loop simply claims again next tick. */
  async claimOutbound(workerId: string, max: number): Promise<OutboundJob[]> {
    const res = await this.post<{ jobs?: OutboundJob[] }>("/messages/outbound/claim", { worker_id: workerId, max });
    return Array.isArray(res.jobs) ? res.jobs : [];
  }

  postResult(jobId: string, result: JobResult, signal?: AbortSignal): Promise<unknown> {
    return this.postWithRetry(`/messages/outbound/${encodeURIComponent(jobId)}/result`, result, {
      attempts: 6,
      baseMs: 500,
      maxMs: 10_000,
      signal,
    });
  }
}
