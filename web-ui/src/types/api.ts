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
}

export interface RunCreatePayload {
  task: string;
  provider: string;
  model?: string;
  max_iters: number;
  skills_dir?: string;
}

export interface SkillItem {
  name: string;
  description: string;
  path: string;
}

export interface StreamEnvelope {
  event: string;
  data: unknown;
}
