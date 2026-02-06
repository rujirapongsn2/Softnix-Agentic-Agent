import type { RunCreatePayload, RunState, SkillItem } from "@/types/api";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8787";
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
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
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
  }
};

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
