// Thin wrappers around the Stage 2 FastAPI job-queue API.
// Every number the UI displays comes from these endpoints — there is
// no local data generation anywhere in this frontend.

async function asJson(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) { /* keep the HTTP status text */ }
    throw new Error(detail);
  }
  return res.json();
}

export async function postJob(path, payload) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  return asJson(res); // { job_id, status: "queued" }
}

export async function getJob(jobId) {
  const res = await fetch(`/api/jobs/${jobId}`);
  return asJson(res); // { job_id, type, status, progress[], error, result, ... }
}

export async function getJobResult(jobId) {
  const res = await fetch(`/api/jobs/${jobId}/result`);
  return asJson(res); // full analyze_target_json payload for analyze jobs
}

export function plateUrl(jobId) {
  return `/api/jobs/${jobId}/plate`;
}

export async function getHistory(limit = 50) {
  const res = await fetch(`/api/history?limit=${limit}`);
  const data = await asJson(res);
  return data.runs || [];
}

export async function getDiscoveries(limit = 100) {
  const res = await fetch(`/api/discoveries?limit=${limit}`);
  const data = await asJson(res);
  return data.discoveries || [];
}
