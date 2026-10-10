import { sleep, type BackendClient, type JobResult, type OutboundJob } from "./backend.ts";
import { errorMessage, log, maskHandle } from "./log.ts";
import type { Transport } from "./transport.ts";

const ATTEMPTED_CAPACITY = 5000;
const CLAIM_ERROR_BACKOFF_MAX_MS = 15_000;

/**
 * Claims outbound jobs and sends each at most once per process. If the backend
 * hands back a job we already attempted (e.g. our result POST was lost and the
 * 60 s lease expired), we re-report the stored result instead of re-sending.
 */
export class OutboundWorker {
  /** job_id -> result; `null` while the send is in flight. */
  private readonly attempted = new Map<string, JobResult | null>();
  /** Results whose POST failed after retries; re-posted at the top of each tick. */
  private readonly unreported = new Map<string, JobResult>();

  constructor(
    private readonly backend: BackendClient,
    private readonly transport: Transport,
    private readonly opts: { workerId: string; pollMs: number; claimMax: number },
  ) {}

  async run(signal: AbortSignal): Promise<void> {
    let claimFailures = 0;
    log.info("outbound worker started", { worker_id: this.opts.workerId, poll_ms: this.opts.pollMs });
    while (!signal.aborted) {
      await this.flushUnreported(signal);

      let jobs: OutboundJob[] = [];
      try {
        jobs = await this.backend.claimOutbound(this.opts.workerId, this.opts.claimMax);
        if (claimFailures > 0) log.info("outbound claim recovered", { after_failures: claimFailures });
        claimFailures = 0;
      } catch (error) {
        claimFailures += 1;
        const delay = Math.min(CLAIM_ERROR_BACKOFF_MAX_MS, this.opts.pollMs * 2 ** Math.min(claimFailures, 4));
        // Log the first failure and then every 10th so a down backend doesn't flood the console.
        if (claimFailures === 1 || claimFailures % 10 === 0) {
          log.warn("outbound claim failed", { failures: claimFailures, retry_in_ms: delay, error: errorMessage(error) });
        }
        await sleep(delay, signal);
        continue;
      }

      for (const [index, job] of jobs.entries()) {
        if (signal.aborted) {
          log.info("shutdown: leaving claimed jobs for lease expiry", {
            job_ids: jobs.slice(index).map((j) => j.job_id),
          });
          break;
        }
        await this.handle(job, signal);
      }

      if (jobs.length < this.opts.claimMax) await sleep(this.opts.pollMs, signal);
    }
    log.info("outbound worker stopped");
  }

  private async handle(job: OutboundJob, signal: AbortSignal): Promise<void> {
    const fields = { job_id: job.job_id, to: maskHandle(job.to_handle), text_length: job.text?.length ?? 0 };

    if (this.attempted.has(job.job_id)) {
      const prior = this.attempted.get(job.job_id);
      log.warn("job re-claimed after a prior attempt; not re-sending", { ...fields, prior_status: prior?.status });
      if (prior) await this.report(job.job_id, prior, signal);
      return;
    }

    if (!job.job_id || !job.to_handle || typeof job.text !== "string" || job.text.length === 0) {
      const result: JobResult = { status: "failed", provider_message_id: null, error: "invalid job: missing to_handle or text" };
      this.remember(job.job_id, result);
      log.error("outbound job invalid", fields);
      await this.report(job.job_id, result, signal);
      return;
    }

    this.remember(job.job_id, null);
    let result: JobResult;
    try {
      const { providerMessageId } = await this.transport.send(job);
      result = { status: "sent", provider_message_id: providerMessageId, error: null };
      log.info("outbound sent", { ...fields, provider_message_id: providerMessageId });
    } catch (error) {
      result = { status: "failed", provider_message_id: null, error: errorMessage(error).slice(0, 500) };
      log.error("outbound send failed", { ...fields, error: result.error });
    }
    this.remember(job.job_id, result);
    await this.report(job.job_id, result, signal);
  }

  private remember(jobId: string, result: JobResult | null): void {
    this.attempted.delete(jobId);
    this.attempted.set(jobId, result);
    while (this.attempted.size > ATTEMPTED_CAPACITY) {
      const oldest = this.attempted.keys().next().value;
      if (oldest === undefined) break;
      this.attempted.delete(oldest);
    }
  }

  private async report(jobId: string, result: JobResult, signal: AbortSignal): Promise<void> {
    try {
      await this.backend.postResult(jobId, result, signal);
      this.unreported.delete(jobId);
    } catch (error) {
      this.unreported.set(jobId, result);
      log.error("outbound result post failed; will retry", { job_id: jobId, error: errorMessage(error) });
    }
  }

  private async flushUnreported(signal: AbortSignal): Promise<void> {
    for (const [jobId, result] of [...this.unreported]) {
      if (signal.aborted) return;
      await this.report(jobId, result, signal);
    }
  }

  /** Called once on shutdown so final results get one more chance to land. */
  async drain(): Promise<void> {
    if (this.unreported.size === 0) return;
    log.info("shutdown: flushing unreported results", { count: this.unreported.size });
    await this.flushUnreported(new AbortController().signal);
  }
}
