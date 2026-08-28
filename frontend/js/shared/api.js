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

export function createReviewRequest(payload) {
  return api("/api/review-requests", { method: "POST", body: JSON.stringify(payload) });
}

export function uploadReviewRecording(requestId, recording) {
  const params = new URLSearchParams({ task: recording.task, label: recording.label });
  if (recording.question) params.set("question", recording.question);
  return api(`/api/review-requests/${requestId}/recordings?${params}`, {
    method: "POST",
    headers: { "Content-Type": recording.type },
    body: recording.blob,
  });
}

export function completeReviewRequest(requestId) {
  return api(`/api/review-requests/${requestId}/complete`, { method: "POST", body: "{}" });
}

export function discardReviewRequest(requestId) {
  return api(`/api/review-requests/${requestId}`, { method: "DELETE" });
}

export function uploadPersonalRecording(run, recording) {
  const params = new URLSearchParams({
    runId: run.id,
    variantId: run.variantId,
    taskNumber: recording.task,
    questionNumber: recording.question || 1,
    label: recording.label,
  });
  return api(`/api/personal-recordings?${params}`, {
    method: "POST",
    headers: { "Content-Type": recording.type },
    body: recording.blob,
  });
}

export function listPersonalRecordings() {
  return api("/api/personal-recordings");
}

export function personalRecordingStreamUrl(recordingId) {
  return `/api/personal-recordings/${encodeURIComponent(recordingId)}`;
}
