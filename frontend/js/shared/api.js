export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof Blob) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.message || payload.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = payload.code || "request_failed";
    error.requestId = payload.requestId || null;
    throw error;
  }
  return payload;
}

export function uploadAudio(submissionId, recording) {
  const params = new URLSearchParams({ task: recording.task, label: recording.label });
  if (recording.question) params.set("question", recording.question);
  return api(`/api/submissions/${submissionId}/recordings?${params}`, {
    method: "POST",
    headers: { "Content-Type": recording.type },
    body: recording.blob,
  });
}
