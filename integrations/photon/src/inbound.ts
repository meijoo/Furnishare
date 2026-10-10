import type { BackendClient, InboundEvent } from "./backend.ts";
import { LruSet } from "./lru.ts";
import { errorMessage, log, maskHandle } from "./log.ts";
import type { InboundHandler } from "./transport.ts";

const SEEN_CAPACITY = 2000;

/**
 * Forwards inbound messages to the backend. The LRU is only a first dedupe
 * layer for provider redeliveries within this process; the backend dedupes
 * durably by event_id, which is also what makes retrying the POST safe.
 */
export function createInboundHandler(backend: BackendClient, signal: AbortSignal): InboundHandler {
  const seen = new LruSet(SEEN_CAPACITY);

  return async (event: InboundEvent) => {
    const fields = {
      event_id: event.event_id,
      sender: maskHandle(event.sender_handle),
      conversation_id: event.conversation_id,
      text_length: event.text.length,
    };
    if (seen.has(event.event_id)) {
      log.debug("inbound duplicate dropped locally", fields);
      return;
    }
    seen.add(event.event_id);
    try {
      const res = await backend.postInbound(event, signal);
      log.info("inbound forwarded", { ...fields, backend_status: res.status });
    } catch (error) {
      // Forget it so a provider redelivery can try again.
      seen.delete(event.event_id);
      log.error("inbound forward failed, message dropped", { ...fields, error: errorMessage(error) });
    }
  };
}
