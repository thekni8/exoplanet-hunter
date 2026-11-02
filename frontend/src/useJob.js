import { useEffect, useRef, useState } from 'react';
import { getJob } from './api.js';

// Polls GET /api/jobs/{id} every ~2s while the job is queued/running.
// Returns { job, pollError } — job is the full status payload
// (status, progress[], error, result summary).
export function useJobPolling(jobId, intervalMs = 2000) {
  const [job, setJob] = useState(null);
  const [pollError, setPollError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setPollError(null);
      return undefined;
    }
    let cancelled = false;
    setJob(null);
    setPollError(null);

    const tick = async () => {
      try {
        const data = await getJob(jobId);
        if (cancelled) return;
        setJob(data);
        setPollError(null);
        if (data.status === 'done' || data.status === 'failed') {
          if (timer.current) clearInterval(timer.current);
        }
      } catch (e) {
        if (!cancelled) setPollError(e.message || String(e));
      }
    };

    tick();
    timer.current = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
    };
  }, [jobId, intervalMs]);

  return { job, pollError };
}
