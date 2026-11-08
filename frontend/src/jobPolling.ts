import { api, HttpError } from './api.ts';
import type { Job, Project } from './types.ts';

type Callbacks = {
  onUpdate: (job: Job, project: Project) => void;
  onFinished: (job: Job) => void;
  onInterrupted: (error: unknown) => void;
  onFatal: (error: unknown) => void;
};

/** Keep the server-owned task alive through temporary transport failures. */
export function createJobPoller(jobId: string, callbacks: Callbacks) {
  let stopped = false;
  let fetching = false;
  let interrupted = false;

  return {
    stop() { stopped = true; },
    async poll() {
      if (stopped || fetching) return;
      fetching = true;
      try {
        const job = await api<Job>(`/jobs/${encodeURIComponent(jobId)}`);
        if (stopped) return;
        const project = await api<Project>(`/projects/${encodeURIComponent(job.project_id)}`);
        if (stopped) return;
        interrupted = false;
        callbacks.onUpdate(job, project);
        if (job.status !== 'running') {
          stopped = true;
          callbacks.onFinished(job);
        }
      } catch (error) {
        if (stopped) return;
        const permanent = error instanceof HttpError
          && error.status >= 400 && error.status < 500
          && ![408, 425, 429].includes(error.status);
        if (permanent) {
          stopped = true;
          callbacks.onFatal(error);
        } else if (!interrupted) {
          interrupted = true;
          callbacks.onInterrupted(error);
        }
      } finally {
        fetching = false;
      }
    },
  };
}
