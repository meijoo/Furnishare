import type { InboundEvent, OutboundJob } from "./backend.ts";

export type InboundHandler = (event: InboundEvent) => Promise<void>;

export interface Transport {
  readonly name: string;
  /** Establish the provider connection. Throws on bad credentials. */
  connect(): Promise<void>;
  /** Deliver inbound messages to `onInbound` (awaited, in order) until the source ends or `stop()` is called. */
  run(onInbound: InboundHandler): Promise<void>;
  /** Send one outbound job. Resolves with the provider's id for the sent message, if it returns one. */
  send(job: OutboundJob): Promise<{ providerMessageId: string | null }>;
  stop(): Promise<void>;
}
