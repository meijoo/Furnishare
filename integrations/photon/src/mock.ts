import readline from "node:readline";
import type { InboundEvent, OutboundJob } from "./backend.ts";
import { log } from "./log.ts";
import type { InboundHandler, Transport } from "./transport.ts";

const LINE = /^\s*([^:\s]+)\s*:\s*(.+?)\s*$/;

/**
 * Stand-in for Photon: stdin lines `+15551234567: my limit for the sofa is $100`
 * become inbound messages; outbound jobs are printed to stdout.
 */
export class MockTransport implements Transport {
  readonly name = "mock";
  private rl: readline.Interface | undefined;
  private counter = 0;

  async connect(): Promise<void> {
    log.info("mock mode: Photon is not contacted. Type `+15551234567: message text` and press Enter.");
  }

  async run(onInbound: InboundHandler): Promise<void> {
    this.rl = readline.createInterface({ input: process.stdin, terminal: false });
    for await (const raw of this.rl) {
      if (!raw.trim()) continue;
      const match = LINE.exec(raw);
      if (!match) {
        log.warn("mock: could not parse line; expected `<handle>: <text>`");
        continue;
      }
      const [, handle, body] = match as unknown as [string, string, string];
      this.counter += 1;
      const event: InboundEvent = {
        event_id: `mock-${process.pid}-${Date.now()}-${this.counter}`,
        sender_handle: handle,
        conversation_id: `any;-;${handle}`,
        text: body,
        received_at: new Date().toISOString(),
      };
      await onInbound(event);
    }
  }

  async send(job: OutboundJob): Promise<{ providerMessageId: string | null }> {
    process.stdout.write(`[outbound ${job.job_id}] -> ${job.to_handle}: ${job.text}\n`);
    return { providerMessageId: `mock-out-${job.job_id}` };
  }

  async stop(): Promise<void> {
    this.rl?.close();
  }
}
