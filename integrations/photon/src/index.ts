import { BackendClient } from "./backend.ts";
import { loadConfig } from "./config.ts";
import { createInboundHandler } from "./inbound.ts";
import { errorMessage, log } from "./log.ts";
import { MockTransport } from "./mock.ts";
import { OutboundWorker } from "./outbound.ts";
import type { Transport } from "./transport.ts";

const SHUTDOWN_TIMEOUT_MS = 15_000;

async function main(): Promise<void> {
  const config = loadConfig();
  const backend = new BackendClient(config.backendUrl);
  const transport: Transport = config.mock
    ? new MockTransport()
    : new (await import("./photon.ts")).PhotonTransport(config);
  const worker = new OutboundWorker(backend, transport, config);

  log.info("starting", {
    transport: transport.name,
    backend_url: config.backendUrl,
    worker_id: config.workerId,
  });

  const controller = new AbortController();
  let shuttingDown = false;
  let outboundDone: Promise<void> = Promise.resolve();
  let inboundDone: Promise<void> = Promise.resolve();

  const shutdown = async (reason: string, exitCode = 0) => {
    if (shuttingDown) return;
    shuttingDown = true;
    log.info("shutting down", { reason });
    setTimeout(() => {
      log.error("shutdown timed out; forcing exit");
      process.exit(1);
    }, SHUTDOWN_TIMEOUT_MS).unref();

    controller.abort();
    await outboundDone;
    await worker.drain();
    try {
      await transport.stop();
    } catch (error) {
      log.warn("transport stop failed", { error: errorMessage(error) });
    }
    await inboundDone;
    log.info("stopped");
    process.exit(exitCode);
  };
  process.once("SIGINT", () => void shutdown("SIGINT"));
  process.once("SIGTERM", () => void shutdown("SIGTERM"));

  await transport.connect();
  if (shuttingDown) return;

  outboundDone = worker.run(controller.signal).catch((error) => {
    log.error("outbound worker crashed", { error: errorMessage(error) });
    void shutdown("outbound worker crashed", 1);
  });

  inboundDone = transport
    .run(createInboundHandler(backend, controller.signal))
    .then(() => {
      if (shuttingDown) return;
      if (config.mock) {
        log.info("mock: stdin closed; still polling outbound. Ctrl-C to exit.");
      } else {
        log.error("inbound stream ended unexpectedly");
        void shutdown("inbound stream ended", 1);
      }
    })
    .catch((error) => {
      log.error("inbound stream failed", { error: errorMessage(error) });
      void shutdown("inbound stream failed", 1);
    });
}

main().catch((error) => {
  log.error("fatal", { error: errorMessage(error) });
  process.exit(1);
});
