import { Spectrum, text, type Content, type Message, type Space } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import type { InboundEvent, OutboundJob } from "./backend.ts";
import { normalizeHandle, type Config } from "./config.ts";
import { errorMessage, log, maskHandle } from "./log.ts";
import type { InboundHandler, Transport } from "./transport.ts";

/** `space.phone` value the iMessage provider uses for Photon's shared (pooled) lines. */
const SHARED_PHONE = "shared";

const createApp = (projectId: string, projectSecret: string) =>
  Spectrum({ projectId, projectSecret, providers: [imessage.config()] });

type App = Awaited<ReturnType<typeof createApp>>;
type IMessageSpace = Space & { type: "dm" | "group"; phone: string };

function extractText(content: Content): string | null {
  switch (content.type) {
    case "text":
      return content.text;
    case "markdown":
      return content.markdown;
    case "group": {
      const parts = content.items.map((item: Message) => extractText(item.content)).filter((t): t is string => !!t);
      return parts.length > 0 ? parts.join("\n") : null;
    }
    default:
      return null;
  }
}

export class PhotonTransport implements Transport {
  readonly name = "photon";
  private app: App | undefined;
  private mode: "shared" | "dedicated" | "unknown" = "unknown";
  /** Which of our dedicated lines last heard from a handle / conversation, so replies come from the same number. */
  private readonly lineForHandle = new Map<string, string>();
  private readonly lineForConversation = new Map<string, string>();

  constructor(private readonly config: Config) {}

  async connect(): Promise<void> {
    this.app = await createApp(this.config.projectId!, this.config.projectSecret!);
    log.info("connected to Photon Spectrum", {
      project: this.app.config.name,
      groups_enabled: this.config.enableGroups,
    });
  }

  /** The SDK exposes no authenticated "which line type am I" call, so infer it from the first inbound space. */
  private noteLineMode(space: IMessageSpace): void {
    if (this.mode !== "unknown") return;
    this.mode = space.phone === SHARED_PHONE ? "shared" : "dedicated";
    log.info("detected iMessage line type", { imessage_mode: this.mode });
    if (this.mode === "shared" && this.config.enableGroups) {
      log.warn("PHOTON_ENABLE_GROUPS is set but shared iMessage lines are DM-only");
    }
  }

  async run(onInbound: InboundHandler): Promise<void> {
    const im = imessage(this.requireApp());
    for await (const [space, message] of im.messages) {
      try {
        const event = this.toInboundEvent(space, message);
        if (event) await onInbound(event);
      } catch (error) {
        log.error("failed to handle inbound message", { message_id: message.id, error: errorMessage(error) });
      }
    }
  }

  private isFromSelf(space: IMessageSpace, message: Message): boolean {
    // The provider already drops isFromMe events; these checks are defense in depth.
    if (message.direction === "outbound") return true;
    const sender = message.sender;
    if (!sender?.id) return true;
    if (sender.kind === "agent") return true;
    const handle = normalizeHandle(sender.id);
    if (space.phone !== SHARED_PHONE && handle === normalizeHandle(space.phone)) return true;
    return this.config.selfHandles.has(handle);
  }

  private toInboundEvent(space: IMessageSpace, message: Message): InboundEvent | null {
    this.noteLineMode(space);
    if (this.isFromSelf(space, message)) {
      log.debug("ignored message from self", { message_id: message.id });
      return null;
    }
    const senderHandle = message.sender!.id;
    if (space.type === "group" && !this.config.enableGroups) {
      log.info("ignored group message (PHOTON_ENABLE_GROUPS=0)", { message_id: message.id, conversation_id: space.id });
      return null;
    }
    const body = extractText(message.content);
    if (body === null || body.trim() === "") {
      log.info("ignored non-text message", { message_id: message.id, content_type: message.content.type });
      return null;
    }
    if (space.phone !== SHARED_PHONE) {
      this.lineForHandle.set(normalizeHandle(senderHandle), space.phone);
      this.lineForConversation.set(space.id, space.phone);
    }
    return {
      event_id: message.id,
      sender_handle: senderHandle,
      conversation_id: space.id,
      text: body,
      received_at: message.timestamp.toISOString(),
    };
  }

  async send(job: OutboundJob): Promise<{ providerMessageId: string | null }> {
    const im = imessage(this.requireApp());
    const conversationId = job.conversation_id ?? "";
    const isGroupTarget = conversationId.includes(";+;");

    let space;
    if (isGroupTarget && this.config.enableGroups) {
      const phone = this.lineForConversation.get(conversationId);
      space = phone ? await im.space.get(conversationId, { phone }) : await im.space.get(conversationId);
    } else {
      if (isGroupTarget) {
        log.info("group conversation_id given but groups disabled; sending as DM", { job_id: job.job_id });
      }
      const phone = this.lineForHandle.get(normalizeHandle(job.to_handle));
      space = phone ? await im.space.create(job.to_handle, { phone }) : await im.space.create(job.to_handle);
    }

    log.debug("resolved outbound space", { job_id: job.job_id, to: maskHandle(job.to_handle), space_type: space.type });
    const sent = await space.send(text(job.text));
    return { providerMessageId: sent?.id ?? null };
  }

  async stop(): Promise<void> {
    await this.app?.stop();
  }

  private requireApp(): App {
    if (!this.app) throw new Error("PhotonTransport.connect() has not completed");
    return this.app;
  }
}
