import type {
  ArtifactEntry,
  MemoryMetrics,
  PendingMemoryItem,
  PolicyReloadResult,
  RunCreatePayload,
  RunState,
  SkillItem
} from "@/types/api";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8787";
const API_KEY = import.meta.env.VITE_SOFTNIX_API_KEY ?? "";
const MEMORY_ADMIN_KEY = import.meta.env.VITE_SOFTNIX_MEMORY_ADMIN_KEY ?? "";
const STREAM_RETRY_MS = 1000;

const runLastEventIds = new Map<string, string>();

function getLastEventId(runId: string): string {
  if (runLastEventIds.has(runId)) return runLastEventIds.get(runId)!;
  try {
    const key = `softnix:last-event-id:${runId}`;
    const v = sessionStorage.getItem(key) ?? "";
    if (v) runLastEventIds.set(runId, v);
    return v;
  } catch {
    return "";
  }
}

function setLastEventId(runId: string, id: string): void {
  if (!id) return;
  runLastEventIds.set(runId, id);
  try {
    sessionStorage.setItem(`softnix:last-event-id:${runId}`, id);
  } catch {
    // ignore storage failures
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authHeaders: Record<string, string> = API_KEY ? { "x-api-key": API_KEY } : {};
  const extraHeaders: Record<string, string> = (init?.headers ?? {}) as Record<string, string>;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...extraHeaders
    }
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return (await res.json()) as T;
}

export const apiClient = {
  baseUrl: API_BASE,

  createRun(payload: RunCreatePayload): Promise<{ run_id: string; status: string; workspace: string }> {
    return request("/runs", { method: "POST", body: JSON.stringify(payload) });
  },

  listRuns(): Promise<{ items: RunState[] }> {
    return request("/runs");
  },

  getRun(runId: string): Promise<RunState> {
    return request(`/runs/${runId}`);
  },

  getRunIterations(runId: string): Promise<{ items: Array<Record<string, unknown>> }> {
    return request(`/runs/${runId}/iterations`);
  },

  getRunEvents(runId: string): Promise<{ items: string[] }> {
    return request(`/runs/${runId}/events`);
  },

  getPendingMemory(runId: string): Promise<{ items: PendingMemoryItem[] }> {
    return request(`/runs/${runId}/memory/pending`);
  },

  getMemoryMetrics(runId: string): Promise<MemoryMetrics> {
    return request(`/runs/${runId}/memory/metrics`);
  },

  confirmPendingMemory(runId: string, key: string, reason = ""): Promise<{ status: string }> {
    return request(`/runs/${runId}/memory/confirm`, {
      method: "POST",
      body: JSON.stringify({ key, reason })
    });
  },

  rejectPendingMemory(runId: string, key: string, reason = ""): Promise<{ status: string }> {
    return request(`/runs/${runId}/memory/reject`, {
      method: "POST",
      body: JSON.stringify({ key, reason })
    });
  },

  getRunArtifacts(runId: string): Promise<{ items: string[]; entries?: ArtifactEntry[] }> {
    return request(`/artifacts/${runId}`);
  },

  artifactDownloadUrl(runId: string, artifactPath: string): string {
    const encodedPath = artifactPath
      .split("/")
      .map((part) => encodeURIComponent(part))
      .join("/");
    const url = new URL(`${API_BASE}/artifacts/${encodeURIComponent(runId)}/${encodedPath}`);
    if (API_KEY) {
      url.searchParams.set("api_key", API_KEY);
    }
    return url.toString();
  },

  cancelRun(runId: string): Promise<{ status: string }> {
    return request(`/runs/${runId}/cancel`, { method: "POST" });
  },

  resumeRun(runId: string): Promise<{ status: string }> {
    return request(`/runs/${runId}/resume`, { method: "POST" });
  },

  getSkills(): Promise<{ items: SkillItem[] }> {
    return request("/skills");
  },

  getHealth(): Promise<{ ok: boolean; providers: Record<string, { ok: boolean; message: string }> }> {
    return request("/health");
  },

  getSystemConfig(): Promise<Record<string, unknown>> {
    return request("/system/config");
  },

  async uploadWorkspaceFile(file: File, path?: string): Promise<{ status: string; path: string; size: number }> {
    const authHeaders: Record<string, string> = API_KEY ? { "x-api-key": API_KEY } : {};
    const contentBase64 = await fileToBase64(file);
    const targetPath = (path ?? "").trim();
    const res = await fetch(`${API_BASE}/files/upload`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders
      },
      body: JSON.stringify({
        filename: file.name,
        content_base64: contentBase64,
        path: targetPath || undefined
      })
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return (await res.json()) as { status: string; path: string; size: number };
  },

  hasMemoryAdminKey(): boolean {
    return Boolean(MEMORY_ADMIN_KEY);
  },

  reloadMemoryPolicy(): Promise<PolicyReloadResult> {
    const headers: Record<string, string> = {};
    if (MEMORY_ADMIN_KEY) headers["x-memory-admin-key"] = MEMORY_ADMIN_KEY;
    return request("/admin/memory/policy/reload", {
      method: "POST",
      headers
    });
  }
};

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function streamRun(
  runId: string,
  handlers: {
    onState?: (state: RunState) => void;
    onIteration?: (item: Record<string, unknown>) => void;
    onEvent?: (entry: { message: string }) => void;
    onDone?: (state: RunState) => void;
    onError?: (error: Event) => void;
  }
): EventSource {
  let closed = false;
  let currentEs: EventSource | null = null;
  let reconnectTimer: number | null = null;

  const connect = () => {
    if (closed) return;
    const lastId = getLastEventId(runId);
    const query = new URLSearchParams({ poll_ms: "500" });
    if (lastId) query.set("last_event_id", lastId);
    if (API_KEY) query.set("api_key", API_KEY);

    const es = new EventSource(`${API_BASE}/runs/${runId}/stream?${query.toString()}`);
    currentEs = es;

    const rememberId = (event: MessageEvent) => {
      if (event.lastEventId) setLastEventId(runId, event.lastEventId);
    };

    es.addEventListener("state", (event) => {
      const msg = event as MessageEvent;
      rememberId(msg);
      handlers.onState?.(JSON.parse(msg.data));
    });
    es.addEventListener("iteration", (event) => {
      const msg = event as MessageEvent;
      rememberId(msg);
      handlers.onIteration?.(JSON.parse(msg.data));
    });
    es.addEventListener("event", (event) => {
      const msg = event as MessageEvent;
      rememberId(msg);
      handlers.onEvent?.(JSON.parse(msg.data));
    });
    es.addEventListener("done", (event) => {
      const msg = event as MessageEvent;
      rememberId(msg);
      handlers.onDone?.(JSON.parse(msg.data));
      closed = true;
      es.close();
    });
    es.onerror = (e) => {
      handlers.onError?.(e);
      es.close();
      if (!closed) {
        reconnectTimer = window.setTimeout(() => {
          connect();
        }, STREAM_RETRY_MS);
      }
    };
  };

  connect();

  const controller = {
    close: () => {
      closed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      currentEs?.close();
    }
  } as unknown as EventSource;
  return controller;
}
