export type RunStatus = "running" | "completed" | "failed" | "canceled";

export interface RunState {
  run_id: string;
  task: string;
  provider: string;
  model: string;
  workspace: string;
  skills_dir: string;
  max_iters: number;
  iteration: number;
  status: RunStatus;
  stop_reason?: string | null;
  created_at?: string;
  updated_at?: string;
  last_output?: string;
  cancel_requested?: boolean;
  selected_skills?: string[];
}

export interface RunCreatePayload {
  task: string;
  provider?: string;
  model?: string;
  max_iters?: number;
  skills_dir?: string;
}

export interface SkillItem {
  name: string;
  description: string;
  path: string;
}

export interface ArtifactEntry {
  path: string;
  size: number;
  modified_at: number;
}

export interface PendingMemoryItem {
  pending_key: string;
  target_key: string;
  value: string;
  priority: number;
  source: string;
  updated_at: string;
}

export interface MemoryMetrics {
  pending_count: number;
  pending_alert_threshold: number;
  pending_backlog_alert: boolean;
  compact_failures: number;
  policy_allow_tools: string[];
}

export interface PolicyReloadResult {
  status: string;
  policy_path: string;
  policy_entry_count: number;
  policy_allow_tools: string[];
  policy_modified_at: number;
}

export interface StreamEnvelope {
  event: string;
  data: unknown;
}
