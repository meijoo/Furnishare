import os from "node:os";
import path from "node:path";
import dotenv from "dotenv";

const PACKAGE_DIR = path.resolve(import.meta.dirname, "..");
const REPO_ROOT = path.resolve(PACKAGE_DIR, "../..");

dotenv.config({ path: path.join(REPO_ROOT, ".env"), quiet: true });
dotenv.config({ path: path.join(PACKAGE_DIR, ".env"), quiet: true });

export interface Config {
  mock: boolean;
  backendUrl: string;
  workerId: string;
  pollMs: number;
  claimMax: number;
  projectId: string | undefined;
  projectSecret: string | undefined;
  selfHandles: Set<string>;
  enableGroups: boolean;
}

function flag(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function int(value: string | undefined, fallback: number): number {
  const n = Number.parseInt(value ?? "", 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function blankToUndefined(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export function normalizeHandle(handle: string): string {
  return handle.trim().toLowerCase();
}

export function loadConfig(argv: string[] = process.argv.slice(2)): Config {
  const env = process.env;
  const config: Config = {
    mock: argv.includes("--mock") || flag(env.MOCK),
    backendUrl: (blankToUndefined(env.BACKEND_URL) ?? "http://127.0.0.1:8000").replace(/\/+$/, ""),
    workerId: blankToUndefined(env.WORKER_ID) ?? `photon-${os.hostname()}-${process.pid}`,
    pollMs: int(env.OUTBOUND_POLL_MS, 1000),
    claimMax: int(env.OUTBOUND_CLAIM_MAX, 10),
    projectId: blankToUndefined(env.PHOTON_PROJECT_ID),
    projectSecret: blankToUndefined(env.PHOTON_PROJECT_SECRET),
    selfHandles: new Set(
      (env.PHOTON_SELF_HANDLES ?? "").split(",").map(normalizeHandle).filter(Boolean),
    ),
    enableGroups: flag(env.PHOTON_ENABLE_GROUPS),
  };

  if (!config.mock && (!config.projectId || !config.projectSecret)) {
    throw new Error(
      "PHOTON_PROJECT_ID and PHOTON_PROJECT_SECRET must be set (repo-root .env), or run with --mock / MOCK=1",
    );
  }
  return config;
}
