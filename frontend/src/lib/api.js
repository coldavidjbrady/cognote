const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function getOverview() {
  return request("/api/overview");
}

export function getAppSettings() {
  return request("/api/settings");
}

export function updateOpenAIKey(apiKey) {
  return request("/api/settings/openai-key", {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function deleteOpenAIKey() {
  return request("/api/settings/openai-key", {
    method: "DELETE",
  });
}

export function getJobStatus() {
  return request("/api/jobs/status");
}

export function startSetupJob(payload = {}) {
  return request("/api/jobs/setup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startSyncJob(payload = {}) {
  return request("/api/jobs/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function searchNotes({ query, mode, collectionId, archivedOnly = false }) {
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }
  if (mode) {
    params.set("mode", mode);
  }
  if (collectionId) {
    params.set("collection_id", String(collectionId));
  }
  if (archivedOnly) {
    params.set("archived_only", "true");
  }
  params.set("limit", "24");
  return request(`/api/search?${params.toString()}`);
}

export function listNotes({ collectionId, archivedOnly = false, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (collectionId) {
    params.set("collection_id", String(collectionId));
  }
  if (archivedOnly) {
    params.set("archived_only", "true");
  }
  if (typeof limit === "number") {
    params.set("limit", String(limit));
  }
  if (typeof offset === "number" && offset > 0) {
    params.set("offset", String(offset));
  }
  const queryString = params.toString();
  return request(queryString ? `/api/notes?${queryString}` : "/api/notes");
}

export function getNote(noteId) {
  return request(`/api/notes/${noteId}`);
}

export function getRelatedNotes(noteId) {
  return request(`/api/notes/${noteId}/related?limit=6`);
}

export function getCollections() {
  return request("/api/collections");
}

export function createCollection(payload) {
  return request("/api/collections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function addNoteToCollection(collectionId, noteId) {
  return request(`/api/collections/${collectionId}/notes`, {
    method: "POST",
    body: JSON.stringify({ note_id: noteId }),
  });
}

export function removeNoteFromCollection(collectionId, noteId) {
  return request(`/api/collections/${collectionId}/notes/${noteId}`, {
    method: "DELETE",
  });
}

export function createNoteLink(payload) {
  return request("/api/links", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteNoteLink(linkId) {
  return request(`/api/links/${linkId}`, {
    method: "DELETE",
  });
}

export function queryAssistant({
  question,
  mode,
  noteId,
  includeLinkedNotes,
  history = [],
  previousResponseId = null,
}) {
  return request("/api/assistant/query", {
    method: "POST",
    body: JSON.stringify({
      question,
      mode,
      note_id: noteId,
      include_linked_notes: includeLinkedNotes,
      history,
      previous_response_id: previousResponseId,
    }),
  });
}
