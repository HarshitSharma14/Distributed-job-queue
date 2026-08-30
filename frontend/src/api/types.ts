export interface Analytics {
  total_jobs: number;
  total_attempts: number;
  average_attempts: number | null;
  terminal_jobs: number;
  terminal_success_rate: number | null;
  average_completion_latency_ms: number | null;
  status_counts: Record<string, number>;
  job_types: Array<{
    job_type_id: string;
    publisher_id: string;
    name: string;
    version: number;
    total_jobs: number;
    status_counts: Record<string, number>;
  }>;
}

export interface JobSummary {
  job_id: string;
  type: string;
  queue: string;
  priority: number;
  status: string;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
}

export interface JobList {
  items: JobSummary[];
  next_cursor: string | null;
}

export interface AdminOverview {
  exact: Analytics;
  operational: {
    available: boolean;
    unavailable_reason: string | null;
    window: string;
    series: Array<{
      metric: string;
      unit: string;
      labels: Record<string, string>;
      points: Array<{ timestamp: string; value: number | null }>;
    }>;
  };
}

export interface WorkerAssignment {
  job_id: string;
  type: string;
  queue: string;
  status: string;
  attempt_number: number;
  max_attempts: number;
  worker_id: string;
  lease_expires_at: string | null;
  assigned_at: string;
}

export interface WorkerAttempt {
  attempt_id: string;
  job_id: string;
  type: string;
  queue: string;
  worker_id: string;
  attempt_number: number;
  attempt_status: string;
  duration_ms: number | null;
  started_at: string;
}
