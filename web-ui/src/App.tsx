import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Bot, Check, Download, LoaderCircle, PauseCircle, PlayCircle, SendHorizontal, X } from "lucide-react";

import { MarkdownStream } from "@/components/ai-elements/markdown-stream";
import { MessageBubble } from "@/components/ai-elements/message-bubble";
import { ThinkingBlock } from "@/components/ai-elements/thinking-block";
import { ToolResultCard } from "@/components/ai-elements/tool-result-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiClient, streamRun } from "@/lib/api-client";
import { cn, formatTime } from "@/lib/utils";
import type { ArtifactEntry, MemoryMetrics, PendingMemoryItem, RunState, SkillItem } from "@/types/api";

type TimelineItem =
  | { id: string; kind: "event"; text: string; at?: string }
  | { id: string; kind: "iteration"; item: Record<string, unknown> }
  | { id: string; kind: "state"; state: RunState };

type RunDiagnostics = {
  runtimeProfile?: string;
  runtimeImage?: string;
  noProgressSignature?: string;
  noProgressActions?: string;
  lastIteration?: number;
  lastIterationDone?: boolean;
};

type CreateRunDefaults = {
  provider: string;
  model: string;
  maxIters: number;
};

function ProcessingIndicator({ text = "Agent is processing" }: { text?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-3 flex items-center gap-3 rounded-xl border border-border bg-secondary/60 px-3 py-2"
    >
      <div className="flex items-center gap-1">
        {[0, 1, 2].map((idx) => (
          <motion.span
            key={idx}
            className="h-2 w-2 rounded-full bg-primary"
            animate={{ y: [0, -5, 0], opacity: [0.5, 1, 0.5] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: idx * 0.12 }}
          />
        ))}
      </div>
      <span className="text-xs text-muted-foreground">{text}</span>
    </motion.div>
  );
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 1024) return `${size} B`;
  const kb = size / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)} MB`;
}

function parseEventLine(line: string): { at?: string; message: string } {
  const m = line.match(/^(\d{4}-\d{2}-\d{2}T[^\s]+)\s+(.*)$/);
  if (!m) return { message: line };
  return { at: m[1], message: m[2] };
}

function prettifyEventMessage(message: string): string {
  const init = message.match(/^run initialized task=(.+)$/);
  if (init) return "Run started";

  const skill = message.match(/^skills selected iteration=(\d+) names=(.+)$/);
  if (skill) return `Iteration ${skill[1]}: selected skills ${skill[2]}`;

  const artifact = message.match(/^artifact saved: (.+)$/);
  if (artifact) return `Artifact saved: ${artifact[1]}`;

  const iter = message.match(/^iteration=(\d+) done=(True|False)$/);
  if (iter) return `Iteration ${iter[1]} finished (${iter[2] === "True" ? "done" : "continue"})`;

  const validationFailed = message.match(/^objective validation failed count=(\d+)$/);
  if (validationFailed) {
    return `Validation failed (${validationFailed[1]} checks). Run is not complete yet.`;
  }

  if (message === "objective validation passed") return "Validation passed";
  if (message === "stopped: max_iters reached") return "Run failed: reached max iterations before objective completed";
  if (message === "stopped by cancel request") return "Run canceled by user request";
  const noProgress = message.match(/^stopped: no_progress detected repeated=(\d+) signature=([a-f0-9]+) actions=(.+)$/);
  if (noProgress) {
    return `Run failed: no progress detected (${noProgress[1]} repeats, sig=${noProgress[2]}, actions=${noProgress[3]})`;
  }
  const runtime = message.match(/^container runtime profile=([a-z]+) image=(.+)$/);
  if (runtime) {
    return `Container runtime selected: profile=${runtime[1]}, image=${runtime[2]}`;
  }

  const metrics = message.match(/^memory metrics pending_count=(\d+)$/);
  if (metrics) return `Memory pending count: ${metrics[1]}`;

  return message;
}

function renderStopReason(stopReason?: string | null): string {
  if (!stopReason) return "unknown";
  if (stopReason === "completed") return "objective completed";
  if (stopReason === "max_iters") return "max iterations reached";
  if (stopReason === "no_progress") return "no progress detected";
  if (stopReason === "canceled") return "canceled";
  if (stopReason === "error") return "runtime error";
  if (stopReason === "interrupted") return "interrupted";
  return stopReason;
}

function runOutcome(run: RunState): { label: string; variant: "default" | "muted" | "danger" } {
  if (run.status === "running") return { label: "running", variant: "muted" };
  if (run.status === "canceled") return { label: "canceled", variant: "muted" };
  if (run.status === "failed" || run.stop_reason === "max_iters" || run.stop_reason === "error") {
    return { label: "failed", variant: "danger" };
  }
  if (run.status === "completed" && run.stop_reason === "completed") {
    return { label: "success", variant: "default" };
  }
  return { label: run.status, variant: "muted" };
}

function extractDiagnostics(items: TimelineItem[]): RunDiagnostics {
  const diagnostics: RunDiagnostics = {};
  for (const item of items) {
    if (item.kind !== "event") continue;
    const runtime = item.text.match(/^Container runtime selected: profile=([^,]+), image=(.+)$/);
    if (runtime) {
      diagnostics.runtimeProfile = runtime[1];
      diagnostics.runtimeImage = runtime[2];
      continue;
    }
    const noProgress = item.text.match(/^Run failed: no progress detected \(\d+ repeats, sig=([a-f0-9]+), actions=(.+)\)$/);
    if (noProgress) {
      diagnostics.noProgressSignature = noProgress[1];
      diagnostics.noProgressActions = noProgress[2];
      continue;
    }
    const iter = item.text.match(/^Iteration (\d+) finished \((done|continue)\)$/);
    if (iter) {
      diagnostics.lastIteration = Number(iter[1]);
      diagnostics.lastIterationDone = iter[2] === "done";
    }
  }
  return diagnostics;
}

function finalSummary(run: RunState | null): { title: string; detail: string; tone: "ok" | "warn" | "neutral" } | null {
  if (!run || run.status === "running") return null;

  if (run.status === "completed" && run.stop_reason === "completed") {
    return {
      title: "Final Result: Success",
      detail: `Objective completed in ${run.iteration} iteration(s).`,
      tone: "ok"
    };
  }

  if (run.status === "failed" && run.stop_reason === "max_iters") {
    return {
      title: "Final Result: Failed",
      detail: `Reached max iterations (${run.max_iters}) before completing objective.`,
      tone: "warn"
    };
  }

  if (run.status === "failed" && run.stop_reason === "no_progress") {
    return {
      title: "Final Result: Failed",
      detail: "Stopped because no progress was detected across repeated iterations.",
      tone: "warn"
    };
  }

  if (run.status === "failed" && run.stop_reason === "error") {
    return {
      title: "Final Result: Failed",
      detail: "Execution stopped due to runtime error.",
      tone: "warn"
    };
  }

  if (run.status === "canceled") {
    return {
      title: "Final Result: Canceled",
      detail: "Run was canceled before objective completion.",
      tone: "neutral"
    };
  }

  return {
    title: "Final Result",
    detail: `status=${run.status}, stop_reason=${renderStopReason(run.stop_reason)}`,
    tone: "neutral"
  };
}

export function App() {
  const [runs, setRuns] = useState<RunState[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [health, setHealth] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [task, setTask] = useState("");
  const [defaults, setDefaults] = useState<CreateRunDefaults>({
    provider: "openai",
    model: "gpt-4o-mini",
    maxIters: 10
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadPath, setUploadPath] = useState("inputs/");
  const [uploadPending, setUploadPending] = useState(false);
  const [uploadInfo, setUploadInfo] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactDownloadingPath, setArtifactDownloadingPath] = useState<string | null>(null);
  const [artifactQuery, setArtifactQuery] = useState("");
  const [artifactSort, setArtifactSort] = useState<"name" | "date" | "size">("date");
  const [showArtifacts, setShowArtifacts] = useState(true);
  const [pendingMemoryItems, setPendingMemoryItems] = useState<PendingMemoryItem[]>([]);
  const [memoryMetrics, setMemoryMetrics] = useState<MemoryMetrics | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryActionKey, setMemoryActionKey] = useState<string | null>(null);
  const [policyReloadInfo, setPolicyReloadInfo] = useState<string>("");
  const [policyReloadError, setPolicyReloadError] = useState<string | null>(null);
  const [policyReloading, setPolicyReloading] = useState(false);

  const streamRef = useRef<EventSource | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);

  const selectedRun = useMemo(() => runs.find((r) => r.run_id === selectedRunId) ?? null, [runs, selectedRunId]);
  const selectedRunSummary = useMemo(() => finalSummary(selectedRun), [selectedRun]);
  const selectedRunDiagnostics = useMemo(() => extractDiagnostics(timeline), [timeline]);
  const canReloadPolicy = apiClient.hasMemoryAdminKey();
  const isSelectedRunRunning = selectedRun?.status === "running" || pending;
  const visibleArtifacts = useMemo(() => {
    const q = artifactQuery.trim().toLowerCase();
    const filtered = artifacts.filter((item) => !q || item.path.toLowerCase().includes(q));
    const sorted = [...filtered];
    if (artifactSort === "name") {
      sorted.sort((a, b) => a.path.localeCompare(b.path));
    } else if (artifactSort === "size") {
      sorted.sort((a, b) => b.size - a.size);
    } else {
      sorted.sort((a, b) => b.modified_at - a.modified_at);
    }
    return sorted;
  }, [artifacts, artifactQuery, artifactSort]);

  useEffect(() => {
    void refreshSideData();
    return () => streamRef.current?.close();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void syncRunsFromExternalTriggers();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedRunId, pending, runs]);

  useEffect(() => {
    if (!selectedRunId) return;
    streamRef.current?.close();
    void refreshArtifacts(selectedRunId);
    void refreshMemoryPanel(selectedRunId);

    streamRef.current = streamRun(selectedRunId, {
      onState: (state) => {
        setRuns((prev) => {
          const has = prev.some((r) => r.run_id === state.run_id);
          if (!has) return [state, ...prev];
          return prev.map((r) => (r.run_id === state.run_id ? state : r));
        });
        pushTimeline({ id: `s-${Date.now()}`, kind: "state", state });
      },
      onIteration: (item) => pushTimeline({ id: `i-${Date.now()}`, kind: "iteration", item }),
      onEvent: (evt) => {
        const parsed = parseEventLine(evt.message);
        pushTimeline({
          id: `e-${Date.now()}`,
          kind: "event",
          text: prettifyEventMessage(parsed.message),
          at: parsed.at
        });
      },
      onDone: async () => {
        await refreshRunsOnly();
        await Promise.all([refreshArtifacts(selectedRunId), refreshMemoryPanel(selectedRunId)]);
      },
      onError: () => void handleStreamError()
    });

    return () => streamRef.current?.close();
  }, [selectedRunId]);

  useEffect(() => {
    const viewport = timelineViewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [timeline, selectedRunId]);

  async function refreshSideData() {
    await Promise.all([refreshRunsOnly(), refreshSkills(), refreshHealth(), refreshSystemConfig()]);
  }

  async function refreshRunsOnly() {
    const runsResp = await apiClient.listRuns();
    setRuns(runsResp.items);
    if (!selectedRunId && runsResp.items.length > 0) {
      setSelectedRunId(runsResp.items[0].run_id);
      await hydrateTimeline(runsResp.items[0].run_id);
    }
  }

  async function syncRunsFromExternalTriggers() {
    if (pending) return;
    const runsResp = await apiClient.listRuns();
    setRuns(runsResp.items);
    if (runsResp.items.length === 0) return;

    const latest = runsResp.items[0];
    if (!selectedRunId) {
      setSelectedRunId(latest.run_id);
      await Promise.all([
        hydrateTimeline(latest.run_id),
        refreshArtifacts(latest.run_id),
        refreshMemoryPanel(latest.run_id)
      ]);
      return;
    }

    if (latest.run_id === selectedRunId) return;
    const current = runs.find((r) => r.run_id === selectedRunId) ?? null;
    if (current?.status === "running") return;
    if (latest.status !== "running") return;

    setSelectedRunId(latest.run_id);
    await Promise.all([
      hydrateTimeline(latest.run_id),
      refreshArtifacts(latest.run_id),
      refreshMemoryPanel(latest.run_id)
    ]);
  }

  async function refreshSkills() {
    const res = await apiClient.getSkills();
    setSkills(res.items);
  }

  async function refreshHealth() {
    const res = await apiClient.getHealth();
    setHealth(res.providers);
  }

  async function refreshSystemConfig() {
    try {
      const config = await apiClient.getSystemConfig();
      const provider = typeof config.provider === "string" && config.provider.trim()
        ? config.provider.trim()
        : "openai";
      const model = typeof config.model === "string" && config.model.trim()
        ? config.model.trim()
        : "gpt-4o-mini";
      const maxItersRaw = Number(config.max_iters);
      const maxIters = Number.isFinite(maxItersRaw) && maxItersRaw >= 1 ? maxItersRaw : 10;
      setDefaults({ provider, model, maxIters });
    } catch {
      // keep fallback defaults
    }
  }

  async function handleStreamError() {
    try {
      await apiClient.getHealth();
      setError(null);
    } catch {
      setError("Stream disconnected. You can refresh run detail.");
    }
  }

  async function hydrateTimeline(runId: string) {
    const [events, iterations] = await Promise.all([apiClient.getRunEvents(runId), apiClient.getRunIterations(runId)]);
    const eventItems = events.items.map((text, idx) => {
      const parsed = parseEventLine(text);
      const ts = parsed.at ? Date.parse(parsed.at) : Number.NaN;
      return {
        id: `event-${idx}`,
        kind: "event" as const,
        text: prettifyEventMessage(parsed.message),
        at: parsed.at,
        ts: Number.isFinite(ts) ? ts : idx
      };
    });
    const iterationItems = iterations.items.map((item, idx) => {
      const rawTs = typeof item.timestamp === "string" ? item.timestamp : "";
      const ts = rawTs ? Date.parse(rawTs) : Number.NaN;
      return {
        id: `iter-${idx}`,
        kind: "iteration" as const,
        item,
        ts: Number.isFinite(ts) ? ts : idx + 1_000_000
      };
    });
    const merged = [...eventItems, ...iterationItems]
      .sort((a, b) => a.ts - b.ts)
      .map(({ ts: _ts, ...rest }) => rest as TimelineItem);
    setTimeline(merged);
  }

  async function refreshArtifacts(runId: string) {
    try {
      setArtifactLoading(true);
      setArtifactError(null);
      const res = await apiClient.getRunArtifacts(runId);
      const entries = Array.isArray(res.entries)
        ? res.entries
        : res.items.map((path) => ({ path, size: 0, modified_at: 0 }));
      setArtifacts(entries);
    } catch (e) {
      setArtifacts([]);
      setArtifactError((e as Error).message);
    } finally {
      setArtifactLoading(false);
    }
  }

  async function refreshMemoryPanel(runId: string) {
    try {
      setMemoryLoading(true);
      setMemoryError(null);
      const [pendingRes, metrics] = await Promise.all([
        apiClient.getPendingMemory(runId),
        apiClient.getMemoryMetrics(runId)
      ]);
      setPendingMemoryItems(Array.isArray(pendingRes.items) ? pendingRes.items : []);
      setMemoryMetrics(metrics);
    } catch (e) {
      setPendingMemoryItems([]);
      setMemoryMetrics(null);
      setMemoryError((e as Error).message);
    } finally {
      setMemoryLoading(false);
    }
  }

  function pushTimeline(item: TimelineItem) {
    setTimeline((prev) => [...prev, item]);
  }

  async function onCreateRun() {
    try {
      const trimmedTask = task.trim();
      if (!trimmedTask) {
        setError("Please enter a task");
        return;
      }
      setPending(true);
      setError(null);
      const created = await apiClient.createRun({
        task: trimmedTask,
        provider: defaults.provider,
        model: defaults.model,
        max_iters: defaults.maxIters
      });
      await refreshRunsOnly();
      setSelectedRunId(created.run_id);
      await Promise.all([
        hydrateTimeline(created.run_id),
        refreshArtifacts(created.run_id),
        refreshMemoryPanel(created.run_id)
      ]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function onUploadWorkspaceFile() {
    if (!uploadFile) {
      setUploadError("Please choose a file");
      return;
    }
    try {
      setUploadPending(true);
      setUploadError(null);
      const cleanedPath = uploadPath.trim();
      const fullPath = cleanedPath.endsWith("/") ? `${cleanedPath}${uploadFile.name}` : cleanedPath;
      const uploaded = await apiClient.uploadWorkspaceFile(uploadFile, fullPath || uploadFile.name);
      setUploadInfo(`uploaded: ${uploaded.path} (${formatBytes(uploaded.size)})`);
      setTask((prev) => {
        const next = prev.trim();
        if (!next) return `อ่านไฟล์ ${uploaded.path} แล้ว extract เฉพาะข้อมูลที่ต้องการ`;
        if (next.includes(uploaded.path)) return prev;
        return `${prev}\nไฟล์อ้างอิง: ${uploaded.path}`;
      });
    } catch (e) {
      setUploadError((e as Error).message);
    } finally {
      setUploadPending(false);
    }
  }

  async function onCancelRun() {
    if (!selectedRunId) return;
    await apiClient.cancelRun(selectedRunId);
    await refreshRunsOnly();
  }

  async function onResumeRun() {
    if (!selectedRunId) return;
    await apiClient.resumeRun(selectedRunId);
    await refreshRunsOnly();
  }

  async function onConfirmPending(key: string) {
    if (!selectedRunId) return;
    try {
      setMemoryActionKey(key);
      await apiClient.confirmPendingMemory(selectedRunId, key, "confirmed from web ui");
      await refreshMemoryPanel(selectedRunId);
    } finally {
      setMemoryActionKey(null);
    }
  }

  async function onRejectPending(key: string) {
    if (!selectedRunId) return;
    try {
      setMemoryActionKey(key);
      await apiClient.rejectPendingMemory(selectedRunId, key, "rejected from web ui");
      await refreshMemoryPanel(selectedRunId);
    } finally {
      setMemoryActionKey(null);
    }
  }

  async function onReloadPolicy() {
    try {
      setPolicyReloading(true);
      setPolicyReloadError(null);
      const res = await apiClient.reloadMemoryPolicy();
      const tools = Array.isArray(res.policy_allow_tools) && res.policy_allow_tools.length > 0
        ? res.policy_allow_tools.join(", ")
        : "(none)";
      setPolicyReloadInfo(`entries=${res.policy_entry_count}, tools=${tools}`);
    } catch (e) {
      setPolicyReloadError((e as Error).message);
    } finally {
      setPolicyReloading(false);
    }
  }

  function onDownloadArtifact(path: string) {
    if (!selectedRunId) return;
    setArtifactDownloadingPath(path);
    window.open(apiClient.artifactDownloadUrl(selectedRunId, path), "_blank", "noopener,noreferrer");
    window.setTimeout(() => setArtifactDownloadingPath((prev) => (prev === path ? null : prev)), 1000);
  }

  function providerBadge(item: { ok: boolean; message: string }) {
    if (item.ok) return { text: "ok", variant: "default" as const };
    const msg = (item.message || "").toLowerCase();
    if (msg.includes("missing") || msg.includes("required") || msg.includes("not configured")) {
      return { text: "not config", variant: "muted" as const };
    }
    return { text: "error", variant: "danger" as const };
  }

  return (
    <div className="mx-auto grid min-h-screen max-w-[1600px] grid-cols-12 gap-4 p-4">
      <aside className="col-span-12 lg:col-span-3">
        <Card className="h-full border-0 shadow-float">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Bot className="h-5 w-5 text-primary" /> Softnix Agentic
            </CardTitle>
            <div className="text-xs text-muted-foreground">Backend: {apiClient.baseUrl}</div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Task</label>
              <Input
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe your objective, expected output files, and constraints..."
              />
              <div className="rounded-md border border-border bg-secondary/40 p-2">
                <div className="mb-2 text-[11px] text-muted-foreground">Upload file to workspace</div>
                <input
                  className="mb-2 block w-full text-xs"
                  type="file"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                />
                <Input
                  value={uploadPath}
                  onChange={(e) => setUploadPath(e.target.value)}
                  placeholder="target path, e.g. inputs/"
                />
                <Button
                  variant="secondary"
                  className="mt-2 w-full"
                  onClick={onUploadWorkspaceFile}
                  disabled={uploadPending}
                >
                  {uploadPending ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Upload
                </Button>
                {uploadInfo ? <div className="mt-2 text-[11px] text-muted-foreground">{uploadInfo}</div> : null}
                {uploadError ? <div className="mt-2 text-[11px] text-red-600">{uploadError}</div> : null}
              </div>
              <div className="text-[11px] text-muted-foreground">
                Runtime defaults are auto-loaded from backend config (.env).
              </div>
              <Button
                className="w-full bg-[#2786C2] text-white hover:bg-[#1F6CB0] focus-visible:ring-[#1F6CB0]"
                onClick={onCreateRun}
                disabled={pending}
              >
                {pending ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : <SendHorizontal className="mr-2 h-4 w-4" />} Start Run
              </Button>
              {pending ? (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="rounded-md bg-primary/10 px-3 py-2 text-xs text-primary"
                >
                  Creating run and connecting stream...
                </motion.div>
              ) : null}
              {error ? <div className="text-xs text-red-600">{error}</div> : null}
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Runs</div>
              <ScrollArea className="h-56 space-y-2 pr-1">
                {runs.map((run) => {
                  const outcome = runOutcome(run);
                  return (
                  <button
                    key={run.run_id}
                    className={cn(
                      "mb-2 w-full rounded-lg border p-3 text-left text-xs transition",
                      selectedRunId === run.run_id ? "border-primary bg-primary/5" : "border-border hover:bg-secondary/70"
                    )}
                    onClick={async () => {
                      setSelectedRunId(run.run_id);
                      await Promise.all([
                        hydrateTimeline(run.run_id),
                        refreshArtifacts(run.run_id),
                        refreshMemoryPanel(run.run_id)
                      ]);
                    }}
                  >
                    <div className="mb-1 font-semibold">{run.run_id}</div>
                    <div className="line-clamp-2 text-muted-foreground">{run.task}</div>
                    {Array.isArray(run.selected_skills) && run.selected_skills.length > 0 ? (
                      <div className="mt-2 line-clamp-1 text-[10px] text-primary">
                        skills: {run.selected_skills.join(", ")}
                      </div>
                    ) : null}
                    <div className="mt-2 flex items-center justify-between">
                      <Badge variant={outcome.variant}>{outcome.label}</Badge>
                      <span className="text-[10px] text-muted-foreground">iter {run.iteration}</span>
                    </div>
                  </button>
                  );
                })}
              </ScrollArea>
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Skills</div>
              <div className="space-y-1 text-xs text-muted-foreground">
                {skills.slice(0, 6).map((skill) => (
                  <div key={skill.path} className="rounded-md bg-secondary px-2 py-1">
                    {skill.name}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pending Memory</div>
              {memoryError ? <div className="mb-2 text-xs text-red-600">{memoryError}</div> : null}
              {memoryLoading ? <div className="mb-2 text-xs text-muted-foreground">Loading memory...</div> : null}
              {memoryMetrics ? (
                <div className="mb-2 rounded-md bg-secondary px-2 py-2 text-[11px] text-muted-foreground">
                  <div>pending: {memoryMetrics.pending_count}</div>
                  <div>compact failures: {memoryMetrics.compact_failures}</div>
                  {memoryMetrics.pending_backlog_alert ? (
                    <div className="text-red-600">
                      backlog alert ({memoryMetrics.pending_count}/{memoryMetrics.pending_alert_threshold})
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="space-y-1 text-xs">
                {pendingMemoryItems.length === 0 && !memoryLoading ? (
                  <div className="rounded-md bg-secondary px-2 py-2 text-muted-foreground">No pending memory</div>
                ) : null}
                {pendingMemoryItems.map((item) => (
                  <div key={item.pending_key} className="rounded-md border border-border bg-secondary/60 p-2">
                    <div className="line-clamp-1 font-medium">{item.target_key}</div>
                    <div className="line-clamp-2 text-[11px] text-muted-foreground">{item.value}</div>
                    <div className="mt-1 flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => onConfirmPending(item.target_key)}
                        disabled={memoryActionKey === item.target_key}
                      >
                        {memoryActionKey === item.target_key ? (
                          <LoaderCircle className="h-3 w-3 animate-spin" />
                        ) : (
                          <Check className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onRejectPending(item.target_key)}
                        disabled={memoryActionKey === item.target_key}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Activity className="h-3 w-3" /> Providers
              </div>
              <div className="space-y-1 text-xs">
                {Object.entries(health).map(([name, item]) => {
                  const badge = providerBadge(item);
                  return (
                    <div key={name} className="flex items-center justify-between rounded-md bg-secondary px-2 py-1">
                      <span>{name}</span>
                      <Badge variant={badge.variant}>{badge.text}</Badge>
                    </div>
                  );
                })}
              </div>
            </div>

            {canReloadPolicy ? (
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Admin Policy</div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onReloadPolicy}
                  disabled={policyReloading}
                  className="w-full"
                >
                  {policyReloading ? <LoaderCircle className="mr-1 h-3 w-3 animate-spin" /> : null}
                  Reload Policy
                </Button>
                {policyReloadInfo ? <div className="mt-2 text-[11px] text-muted-foreground">{policyReloadInfo}</div> : null}
                {policyReloadError ? <div className="mt-2 text-[11px] text-red-600">{policyReloadError}</div> : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </aside>

      <main className={cn("col-span-12", showArtifacts ? "lg:col-span-6" : "lg:col-span-9")}>
        <Card className="h-full border-0 bg-white/85 shadow-float backdrop-blur">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-lg">Conversation Timeline</CardTitle>
                  <div className="text-xs text-muted-foreground">
                    {selectedRun ? `${selectedRun.run_id} · ${runOutcome(selectedRun).label} · updated ${formatTime(selectedRun.updated_at)}` : "No run selected"}
                  </div>
                  {selectedRun ? (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      stop reason: {renderStopReason(selectedRun.stop_reason)}
                    </div>
                  ) : null}
                  {selectedRun && Array.isArray(selectedRun.selected_skills) && selectedRun.selected_skills.length > 0 ? (
                    <div className="mt-1 text-[11px] text-primary">skills: {selectedRun.selected_skills.join(", ")}</div>
                  ) : null}
                  {isSelectedRunRunning ? (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 1.2, repeat: Infinity }}
                      className="mt-1 text-[11px] font-medium text-primary"
                    >
                      Live processing...
                    </motion.div>
                  ) : null}
                </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => setShowArtifacts((prev) => !prev)}>
                {showArtifacts ? "Hide Artifacts" : "Show Artifacts"}
              </Button>
              <Button variant="secondary" size="sm" onClick={onResumeRun} disabled={!selectedRunId}>
                <PlayCircle className="mr-1 h-4 w-4" /> Resume
              </Button>
              <Button variant="ghost" size="sm" onClick={onCancelRun} disabled={!selectedRunId}>
                <PauseCircle className="mr-1 h-4 w-4" /> Cancel
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {selectedRunSummary ? (
              <div
                className={cn(
                  "mb-3 rounded-lg border px-3 py-2 text-sm",
                  selectedRunSummary.tone === "ok" && "border-green-200 bg-green-50 text-green-800",
                  selectedRunSummary.tone === "warn" && "border-red-200 bg-red-50 text-red-800",
                  selectedRunSummary.tone === "neutral" && "border-border bg-secondary/60 text-foreground"
                )}
              >
                <div className="font-semibold">{selectedRunSummary.title}</div>
                <div className="text-xs">{selectedRunSummary.detail}</div>
              </div>
            ) : null}
            {selectedRun ? (
              <div className="mb-3 rounded-lg border border-border bg-secondary/50 px-3 py-2 text-xs">
                <div className="mb-1 font-semibold">Run Diagnostics</div>
                <div className="text-muted-foreground">run_id: {selectedRun.run_id}</div>
                <div className="text-muted-foreground">
                  status: {runOutcome(selectedRun).label} / stop_reason: {renderStopReason(selectedRun.stop_reason)}
                </div>
                {selectedRunDiagnostics.runtimeProfile && selectedRunDiagnostics.runtimeImage ? (
                  <div className="text-muted-foreground">
                    runtime: {selectedRunDiagnostics.runtimeProfile} ({selectedRunDiagnostics.runtimeImage})
                  </div>
                ) : null}
                {typeof selectedRunDiagnostics.lastIteration === "number" ? (
                  <div className="text-muted-foreground">
                    last iteration: {selectedRunDiagnostics.lastIteration} ({selectedRunDiagnostics.lastIterationDone ? "done" : "continue"})
                  </div>
                ) : null}
                {selectedRunDiagnostics.noProgressSignature ? (
                  <div className="text-red-700">
                    no-progress: sig={selectedRunDiagnostics.noProgressSignature}, actions={selectedRunDiagnostics.noProgressActions}
                  </div>
                ) : null}
              </div>
            ) : null}
            <ScrollArea ref={timelineViewportRef} className="h-[76vh] space-y-3 pr-2">
              <AnimatePresence>
                {timeline.map((item) => (
                  <motion.div key={item.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mb-3">
                    {item.kind === "event" ? (
                      <MessageBubble role="system" timestamp={formatTime(item.at)}>
                        {item.text}
                      </MessageBubble>
                    ) : null}

                    {item.kind === "state" ? (
                      <MessageBubble role="assistant" timestamp={formatTime(item.state.updated_at)}>
                        <ThinkingBlock
                          text={`state: ${runOutcome(item.state).label}, iteration=${item.state.iteration}, stop_reason=${renderStopReason(item.state.stop_reason)}`}
                        />
                      </MessageBubble>
                    ) : null}

                    {item.kind === "iteration" ? (
                      <MessageBubble
                        role="assistant"
                        timestamp={formatTime(typeof item.item.timestamp === "string" ? item.item.timestamp : undefined)}
                      >
                        <div className="space-y-3">
                          <MarkdownStream content={String(item.item.output ?? "")} />
                          {Array.isArray(item.item.action_results)
                            ? (item.item.action_results as Array<Record<string, unknown>>).map((tool, idx) => (
                                <ToolResultCard
                                  key={`${item.id}-${idx}`}
                                  name={String(tool.name ?? "tool")}
                                  ok={Boolean(tool.ok)}
                                  output={String(tool.output ?? "")}
                                  error={tool.error ? String(tool.error) : null}
                                />
                              ))
                            : null}
                        </div>
                      </MessageBubble>
                    ) : null}
                  </motion.div>
                ))}
                {isSelectedRunRunning ? <ProcessingIndicator /> : null}
              </AnimatePresence>
            </ScrollArea>
          </CardContent>
        </Card>
      </main>

      <AnimatePresence initial={false}>
        {showArtifacts ? (
          <motion.aside
            key="artifacts-sidebar"
            className="col-span-12 lg:col-span-3"
            initial={{ opacity: 0, x: 36 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 36 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <Card className="h-full border-0 shadow-float">
              <CardHeader>
                <CardTitle className="text-lg">Artifacts</CardTitle>
                <div className="text-xs text-muted-foreground">
                  {selectedRun ? `Run: ${selectedRun.run_id}` : "Select a run to view artifacts"}
                </div>
              </CardHeader>
            <CardContent>
              <div className="mb-3 grid grid-cols-3 gap-2">
                <Input
                  className="col-span-2"
                  placeholder="Search artifacts"
                  value={artifactQuery}
                  onChange={(e) => setArtifactQuery(e.target.value)}
                />
                <select
                  className="h-10 rounded-md border border-input bg-background px-3 text-xs"
                  value={artifactSort}
                  onChange={(e) => setArtifactSort(e.target.value as "name" | "date" | "size")}
                >
                  <option value="date">Date</option>
                  <option value="name">Name</option>
                  <option value="size">Size</option>
                </select>
              </div>
              {artifactError ? <div className="mb-3 text-xs text-red-600">{artifactError}</div> : null}
              {!artifactError && artifactLoading ? <div className="mb-3 text-xs text-muted-foreground">Loading artifacts...</div> : null}
              {!artifactError && !artifactLoading && selectedRunId && artifacts.length === 0 ? (
                <div className="text-xs text-muted-foreground">No artifacts yet</div>
              ) : null}
              {!selectedRunId ? <div className="text-xs text-muted-foreground">No run selected</div> : null}
              {!artifactError && !artifactLoading && selectedRunId && artifacts.length > 0 && visibleArtifacts.length === 0 ? (
                <div className="text-xs text-muted-foreground">No artifacts match your search</div>
              ) : null}

              <div className="space-y-2">
                {selectedRunId
                  ? visibleArtifacts.map((artifact) => (
                      <button
                        key={artifact.path}
                        type="button"
                        onClick={() => onDownloadArtifact(artifact.path)}
                        className="flex w-full items-center justify-between rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs transition hover:bg-secondary"
                      >
                        <span className="min-w-0 flex-1 pr-2 text-left">
                          <span className="block truncate">{artifact.path}</span>
                          <span className="block text-[10px] text-muted-foreground">
                            {formatBytes(artifact.size)} · {artifact.modified_at > 0 ? new Date(artifact.modified_at * 1000).toLocaleString() : "unknown time"}
                          </span>
                        </span>
                        <span className="shrink-0 text-primary">
                          {artifactDownloadingPath === artifact.path ? (
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                          ) : (
                            <Download className="h-4 w-4" />
                          )}
                        </span>
                      </button>
                    ))
                  : null}
              </div>
              </CardContent>
            </Card>
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
