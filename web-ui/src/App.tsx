import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Bot, Download, LoaderCircle, PauseCircle, PlayCircle, SendHorizontal } from "lucide-react";

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
import type { RunState, SkillItem } from "@/types/api";

type TimelineItem =
  | { id: string; kind: "event"; text: string }
  | { id: string; kind: "iteration"; item: Record<string, unknown> }
  | { id: string; kind: "state"; state: RunState };

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

export function App() {
  const [runs, setRuns] = useState<RunState[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [health, setHealth] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [task, setTask] = useState("Write html javascript for landing page portfolio");
  const [provider, setProvider] = useState("claude");
  const [model, setModel] = useState("claude-sonnet-4-5");
  const [maxIters, setMaxIters] = useState(10);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [showArtifacts, setShowArtifacts] = useState(true);

  const streamRef = useRef<EventSource | null>(null);
  const timelineViewportRef = useRef<HTMLDivElement | null>(null);

  const selectedRun = useMemo(() => runs.find((r) => r.run_id === selectedRunId) ?? null, [runs, selectedRunId]);
  const isSelectedRunRunning = selectedRun?.status === "running" || pending;

  useEffect(() => {
    void refreshSideData();
    return () => streamRef.current?.close();
  }, []);

  useEffect(() => {
    if (!selectedRunId) return;
    streamRef.current?.close();
    void refreshArtifacts(selectedRunId);

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
      onEvent: (evt) => pushTimeline({ id: `e-${Date.now()}`, kind: "event", text: evt.message }),
      onDone: async () => {
        await refreshRunsOnly();
        await refreshArtifacts(selectedRunId);
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
    await Promise.all([refreshRunsOnly(), refreshSkills(), refreshHealth()]);
  }

  async function refreshRunsOnly() {
    const runsResp = await apiClient.listRuns();
    setRuns(runsResp.items);
    if (!selectedRunId && runsResp.items.length > 0) {
      setSelectedRunId(runsResp.items[0].run_id);
      await hydrateTimeline(runsResp.items[0].run_id);
    }
  }

  async function refreshSkills() {
    const res = await apiClient.getSkills();
    setSkills(res.items);
  }

  async function refreshHealth() {
    const res = await apiClient.getHealth();
    setHealth(res.providers);
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

    const merged: TimelineItem[] = [
      ...events.items.map((text, idx) => ({ id: `event-${idx}`, kind: "event" as const, text })),
      ...iterations.items.map((item, idx) => ({ id: `iter-${idx}`, kind: "iteration" as const, item }))
    ];
    setTimeline(merged);
  }

  async function refreshArtifacts(runId: string) {
    try {
      setArtifactError(null);
      const res = await apiClient.getRunArtifacts(runId);
      setArtifacts(res.items);
    } catch (e) {
      setArtifacts([]);
      setArtifactError((e as Error).message);
    }
  }

  function pushTimeline(item: TimelineItem) {
    setTimeline((prev) => [...prev, item]);
  }

  async function onCreateRun() {
    try {
      setPending(true);
      setError(null);
      const created = await apiClient.createRun({
        task,
        provider,
        model,
        max_iters: maxIters
      });
      await refreshRunsOnly();
      setSelectedRunId(created.run_id);
      await Promise.all([hydrateTimeline(created.run_id), refreshArtifacts(created.run_id)]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
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
              <Input value={task} onChange={(e) => setTask(e.target.value)} />
              <div className="grid grid-cols-2 gap-2">
                <Input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="provider" />
                <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model" />
              </div>
              <Input
                type="number"
                min={1}
                max={50}
                value={maxIters}
                onChange={(e) => setMaxIters(Number(e.target.value || 10))}
              />
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
                {runs.map((run) => (
                  <button
                    key={run.run_id}
                    className={cn(
                      "mb-2 w-full rounded-lg border p-3 text-left text-xs transition",
                      selectedRunId === run.run_id ? "border-primary bg-primary/5" : "border-border hover:bg-secondary/70"
                    )}
                    onClick={async () => {
                      setSelectedRunId(run.run_id);
                      await Promise.all([hydrateTimeline(run.run_id), refreshArtifacts(run.run_id)]);
                    }}
                  >
                    <div className="mb-1 font-semibold">{run.run_id}</div>
                    <div className="line-clamp-2 text-muted-foreground">{run.task}</div>
                    <div className="mt-2 flex items-center justify-between">
                      <Badge variant={run.status === "failed" ? "danger" : "muted"}>{run.status}</Badge>
                      <span className="text-[10px] text-muted-foreground">iter {run.iteration}</span>
                    </div>
                  </button>
                ))}
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
          </CardContent>
        </Card>
      </aside>

      <main className={cn("col-span-12", showArtifacts ? "lg:col-span-6" : "lg:col-span-9")}>
        <Card className="h-full border-0 bg-white/85 shadow-float backdrop-blur">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-lg">Conversation Timeline</CardTitle>
                  <div className="text-xs text-muted-foreground">
                    {selectedRun ? `${selectedRun.run_id} · ${selectedRun.status} · updated ${formatTime(selectedRun.updated_at)}` : "No run selected"}
                  </div>
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
            <ScrollArea ref={timelineViewportRef} className="h-[76vh] space-y-3 pr-2">
              <AnimatePresence>
                {timeline.map((item) => (
                  <motion.div key={item.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mb-3">
                    {item.kind === "event" ? (
                      <MessageBubble role="system" timestamp={new Date().toLocaleTimeString()}>
                        {item.text}
                      </MessageBubble>
                    ) : null}

                    {item.kind === "state" ? (
                      <MessageBubble role="assistant" timestamp={formatTime(item.state.updated_at)}>
                        <ThinkingBlock text={`status=${item.state.status}, iteration=${item.state.iteration}`} />
                      </MessageBubble>
                    ) : null}

                    {item.kind === "iteration" ? (
                      <MessageBubble role="assistant" timestamp={new Date().toLocaleTimeString()}>
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
                {artifactError ? <div className="mb-3 text-xs text-red-600">{artifactError}</div> : null}
                {!artifactError && selectedRunId && artifacts.length === 0 ? (
                  <div className="text-xs text-muted-foreground">No artifacts yet</div>
                ) : null}
                {!selectedRunId ? <div className="text-xs text-muted-foreground">No run selected</div> : null}

                <div className="space-y-2">
                  {selectedRunId
                    ? artifacts.map((artifact) => (
                        <a
                          key={artifact}
                          href={apiClient.artifactDownloadUrl(selectedRunId, artifact)}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center justify-between rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs transition hover:bg-secondary"
                        >
                          <span className="truncate pr-2">{artifact}</span>
                          <span className="shrink-0 text-primary">
                            <Download className="h-4 w-4" />
                          </span>
                        </a>
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
