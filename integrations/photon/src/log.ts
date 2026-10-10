type Level = "debug" | "info" | "warn" | "error";

const ORDER: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

function threshold(): number {
  const raw = (process.env.LOG_LEVEL ?? "info").toLowerCase();
  return ORDER[raw as Level] ?? ORDER.info;
}

/**
 * One JSON object per line on stderr, so stdout stays free for mock-mode output.
 * Callers must never pass secrets or message bodies in `fields`.
 */
function emit(level: Level, msg: string, fields: Record<string, unknown> = {}): void {
  if (ORDER[level] < threshold()) return;
  const line = { ts: new Date().toISOString(), level, component: "photon-adapter", msg, ...fields };
  process.stderr.write(JSON.stringify(line) + "\n");
}

export const log = {
  debug: (msg: string, fields?: Record<string, unknown>) => emit("debug", msg, fields),
  info: (msg: string, fields?: Record<string, unknown>) => emit("info", msg, fields),
  warn: (msg: string, fields?: Record<string, unknown>) => emit("warn", msg, fields),
  error: (msg: string, fields?: Record<string, unknown>) => emit("error", msg, fields),
};

/** `+15551234567` -> `+1555***4567`, `alex@icloud.com` -> `al***@icloud.com`. */
export function maskHandle(handle: string | undefined | null): string {
  if (!handle) return "<none>";
  const at = handle.indexOf("@");
  if (at > 0) return `${handle.slice(0, Math.min(2, at))}***${handle.slice(at)}`;
  if (handle.length <= 6) return "***";
  return `${handle.slice(0, 5)}***${handle.slice(-4)}`;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
