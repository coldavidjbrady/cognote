import { useEffect, useMemo, useState } from "react";
import { formatCollectionCount, formatDateValue } from "../lib/date";

function NoteParagraphs({ text }) {
  const paragraphs = useMemo(() => {
    return (text || "")
      .split(/\n{2,}/)
      .map((part) => part.trim())
      .filter(Boolean);
  }, [text]);

  if (!paragraphs.length) {
    return <p className="muted">This note does not contain visible plain text yet.</p>;
  }

  return (
    <div className="note-body">
      {paragraphs.map((paragraph) => (
        <p key={paragraph.slice(0, 40)}>{paragraph}</p>
      ))}
    </div>
  );
}

function buildThreadMessage(role, content, extra = {}) {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    role,
    content,
    ...extra,
  };
}

function AssistantMessageCard({ message }) {
  const retrievedCount = (message.contextNotes || []).filter((item) => item.kind === "retrieved").length;

  return (
    <article className={`assistant-message assistant-message--${message.role}`}>
      <div className="assistant-message__header">
        <div className="assistant-message__identity">
          <span className="assistant-speaker">
            {message.role === "assistant" ? "Assistant" : "You"}
          </span>
          {message.model ? <span className="assistant-pill">{message.model}</span> : null}
          {message.usedNoteContext ? <span className="assistant-pill">Note context</span> : null}
          {retrievedCount > 0 ? <span className="assistant-pill">RAG +{retrievedCount}</span> : null}
          {message.usedWebSearch ? <span className="assistant-pill assistant-pill--web">Web</span> : null}
        </div>
      </div>

      <div className="assistant-message__body">{message.content}</div>

      {message.webSources?.length ? (
        <div className="assistant-links">
          {message.webSources.map((source) => (
            <a
              key={source.url}
              className="assistant-link"
              href={source.url}
              target="_blank"
              rel="noreferrer"
            >
              {source.title || source.url}
            </a>
          ))}
        </div>
      ) : null}

      {message.contextNotes?.length ? (
        <div className="assistant-context-chips">
          {message.contextNotes.map((item) => (
            <span key={`${item.kind}-${item.id}`} className="assistant-context-chip">
              {item.kind === "selected"
                ? "Open note"
                : item.kind === "linked"
                  ? "Linked"
                  : "Retrieved"}
              <strong>{item.title}</strong>
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export default function NoteDetail({
  note,
  related,
  allCollections,
  assistantEnabled,
  assistantResetKey,
  onAskAssistant,
  onAddToCollection,
  onRemoveFromCollection,
  onCreateCollection,
  onDeleteLink,
}) {
  const [selectedCollection, setSelectedCollection] = useState("");
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionDescription, setNewCollectionDescription] = useState("");
  const [newCollectionColor, setNewCollectionColor] = useState("#315c4a");
  const [assistantMode, setAssistantMode] = useState(note ? "note" : "general");
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantThreads, setAssistantThreads] = useState({
    general: { messages: [], previousResponseId: null },
  });
  const [assistantError, setAssistantError] = useState("");
  const [isAskingAssistant, setIsAskingAssistant] = useState(false);
  const [includeLinkedNotes, setIncludeLinkedNotes] = useState(true);

  const collectionIds = new Set((note?.collections || []).map((collection) => collection.id));
  const availableCollections = allCollections.filter(
    (collection) => !collectionIds.has(collection.id),
  );
  const canUseNoteContext = Boolean(note);
  const isNoteMode = assistantMode === "note";
  const trimmedAssistantQuestion = assistantQuestion.trim();
  const noteThreadKey = note
    ? `note:${note.id}:${includeLinkedNotes ? "with-links" : "selected-only"}`
    : "note:none";
  const activeThreadKey = isNoteMode ? noteThreadKey : "general";
  const activeThreadState = assistantThreads[activeThreadKey] || {
    messages: [],
    previousResponseId: null,
  };
  const activeThread = activeThreadState.messages;
  const latestAssistantMessage = [...activeThread].reverse().find((item) => item.role === "assistant") || null;

  const contextNotes = useMemo(() => {
    if (!note) {
      return [];
    }

    const currentContextNotes = [
      {
        id: note.id,
        title: note.title || "Untitled note",
        kind: "selected",
      },
    ];

    if (!includeLinkedNotes) {
      return currentContextNotes;
    }

    const seenLinkedIds = new Set([note.id]);
    for (const linked of note.manual_links || []) {
      if (seenLinkedIds.has(linked.note_id)) {
        continue;
      }
      seenLinkedIds.add(linked.note_id);
      currentContextNotes.push({
        id: linked.note_id,
        title: linked.title || "Untitled note",
        kind: "linked",
      });
    }

    return currentContextNotes;
  }, [includeLinkedNotes, note]);

  useEffect(() => {
    if (!note && assistantMode === "note") {
      setAssistantMode("general");
    }
  }, [assistantMode, note]);

  useEffect(() => {
    setAssistantQuestion("");
    setAssistantThreads({ general: { messages: [], previousResponseId: null } });
    setAssistantError("");
    setIsAskingAssistant(false);
  }, [assistantResetKey]);

  const handleAddCollection = () => {
    if (!note || !selectedCollection) {
      return;
    }
    onAddToCollection(Number(selectedCollection), note.id);
    setSelectedCollection("");
  };

  const handleCreateCollection = () => {
    if (!note || !newCollectionName.trim()) {
      return;
    }
    onCreateCollection({
      name: newCollectionName.trim(),
      description: newCollectionDescription.trim(),
      color: newCollectionColor,
      note_ids: [note.id],
    });
    setNewCollectionName("");
    setNewCollectionDescription("");
  };

  const handleAssistantSubmit = async () => {
    if (!assistantEnabled || !trimmedAssistantQuestion) {
      return;
    }
    if (isNoteMode && !note) {
      setAssistantError("Open a note before asking with note context.");
      return;
    }

    const userMessage = buildThreadMessage("user", trimmedAssistantQuestion);
    const history = activeThread.map((item) => ({
      role: item.role,
      content: item.content,
    }));

    setIsAskingAssistant(true);
    setAssistantError("");

    try {
      const payload = await onAskAssistant({
        question: trimmedAssistantQuestion,
        mode: assistantMode,
        noteId: note?.id ?? null,
        includeLinkedNotes,
        history,
        previousResponseId: activeThreadState.previousResponseId,
      });

      const assistantMessage = buildThreadMessage("assistant", payload.answer, {
        model: payload.model,
        usedWebSearch: payload.used_web_search,
        usedNoteContext: payload.used_note_context,
        webSources: payload.web_sources || [],
        contextNotes: payload.context_notes || [],
      });

      setAssistantThreads((current) => ({
        ...current,
        [activeThreadKey]: {
          messages: [
            ...(current[activeThreadKey]?.messages || []),
            userMessage,
            assistantMessage,
          ],
          previousResponseId: payload.response_id || current[activeThreadKey]?.previousResponseId || null,
        },
      }));
      setAssistantQuestion("");
    } catch (error) {
      setAssistantError(error.message);
    } finally {
      setIsAskingAssistant(false);
    }
  };

  const handleAssistantKeyDown = (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      handleAssistantSubmit();
    }
  };

  return (
    <section className="detail-panel">
      <section className="detail-section">
        {note ? (
          <header className="detail-header">
            <div>
              <div className="detail-header__row">
                <p className="eyebrow">{note.folder}</p>
                {note.is_archived ? <span className="status-pill archived">Archived locally</span> : null}
              </div>
              <h2>{note.title || "Untitled note"}</h2>
              <div className="meta-row">
                <span>Created {formatDateValue(note, "created_at_iso", "created_at_display")}</span>
                <span>Modified {formatDateValue(note, "modified_at_iso", "modified_at_display")}</span>
                {note.is_archived && note.archived_at ? (
                  <span>Archived {formatDateValue(note, "archived_at", "archived_at")}</span>
                ) : null}
                <span>{note.word_count} words</span>
                <span>{note.char_count} characters</span>
              </div>
            </div>
          </header>
        ) : (
          <div className="empty-state empty-state--detail">
            <h2>No note selected</h2>
            <p>Open a note to chat with grounded context, or ask the assistant a general question.</p>
          </div>
        )}
      </section>

      {note ? (
        <section className="detail-section reading-surface">
          <div className="panel-header">
            <h3>Reading view</h3>
            <span className="muted">{note.account}</span>
          </div>
          <NoteParagraphs text={note.body_text} />
        </section>
      ) : null}

      <section className="detail-section detail-section--assistant">
        <div className="panel-header">
          <h3>Assistant workspace</h3>
          <span className="muted">
            {latestAssistantMessage?.usedWebSearch
              ? "Conversation can use live web results"
              : latestAssistantMessage?.usedNoteContext
                ? "Conversation grounded in your notes"
                : "Conversation memory stays within this search view"}
          </span>
        </div>

        <div className="assistant-panel">
          <div className="assistant-toolbar">
            <div className="assistant-mode-switcher" role="tablist" aria-label="Assistant mode">
              <button
                className={`mode-pill ${assistantMode === "note" ? "active" : ""}`}
                onClick={() => setAssistantMode("note")}
                type="button"
                disabled={!canUseNoteContext}
              >
                With note context
              </button>
              <button
                className={`mode-pill ${assistantMode === "general" ? "active" : ""}`}
                onClick={() => setAssistantMode("general")}
                type="button"
              >
                General chat
              </button>
            </div>

            <div className="assistant-context-card">
              <div className="assistant-context-row">
                <strong>{isNoteMode ? "Grounding" : "Mode"}</strong>
                <span className="muted">
                  {isNoteMode
                    ? `Starting with ${contextNotes.length} note${contextNotes.length === 1 ? "" : "s"}`
                    : "No note context is injected"}
                </span>
              </div>

              {isNoteMode ? (
                <>
                  <label className="assistant-toggle">
                    <input
                      type="checkbox"
                      checked={includeLinkedNotes}
                      onChange={(event) => setIncludeLinkedNotes(event.target.checked)}
                    />
                    <span>Include linked notes</span>
                  </label>
                  <p className="muted assistant-context-copy">
                    Follow-up questions keep their conversation history, and semantically relevant notes
                    can be pulled in automatically for stronger answers.
                  </p>
                  <div className="assistant-context-chips">
                    {contextNotes.map((item) => (
                      <span key={`${item.kind}-${item.id}`} className="assistant-context-chip">
                        {item.kind === "selected" ? "Open note" : "Linked"}
                        <strong>{item.title}</strong>
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <p className="muted assistant-context-copy">
                  General chat keeps its own follow-up memory and can use web search for current events
                  or live information when useful.
                </p>
              )}
            </div>
          </div>

          <div className="assistant-thread-shell">
            <div className="assistant-thread">
              {activeThread.length ? (
                activeThread.map((message) => (
                  <AssistantMessageCard key={message.id} message={message} />
                ))
              ) : (
                <div className="empty-state empty-state--assistant">
                  <h3>Conversation window</h3>
                  <p>
                    {isNoteMode
                      ? "Ask about the open note, linked notes, or let the assistant pull in relevant notes automatically."
                      : "Ask a general question here. Follow-up questions stay in this thread until you run a new search."}
                  </p>
                </div>
              )}
            </div>

            {assistantError ? <p className="assistant-error">{assistantError}</p> : null}
            {!assistantEnabled ? (
              <p className="muted">Set `OPENAI_API_KEY` to enable the assistant workspace.</p>
            ) : null}

            <div className="assistant-composer">
              <textarea
                className="assistant-input"
                placeholder={
                  isNoteMode
                    ? "Ask a follow-up, compare notes, extract actions, or test note-grounded Q&A..."
                    : "Ask a general question, like today's top headlines..."
                }
                value={assistantQuestion}
                onChange={(event) => setAssistantQuestion(event.target.value)}
                onKeyDown={handleAssistantKeyDown}
                rows={4}
              />

              <div className="assistant-actions">
                <button
                  className="primary-button"
                  onClick={handleAssistantSubmit}
                  type="button"
                  disabled={
                    !assistantEnabled ||
                    isAskingAssistant ||
                    !trimmedAssistantQuestion ||
                    (isNoteMode && !canUseNoteContext)
                  }
                >
                  {isAskingAssistant ? "Thinking..." : "Send"}
                </button>
                <span className="muted">Press Cmd/Ctrl + Enter to send</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {note ? (
        <>
          <section className="detail-section">
            <div className="panel-header">
              <h3>Collections</h3>
              <span className="muted">
                {formatCollectionCount((note.collections || []).length)}
              </span>
            </div>
            <div className="chip-row">
              {(note.collections || []).map((collection) => (
                <span
                  key={collection.id}
                  className="collection-chip"
                  style={{ borderColor: collection.color }}
                >
                  {collection.name}
                  <button
                    className="chip-remove"
                    onClick={() => onRemoveFromCollection(collection.id, note.id)}
                    type="button"
                  >
                    Remove
                  </button>
                </span>
              ))}
            </div>
            <div className="inline-form">
              <select
                value={selectedCollection}
                onChange={(event) => setSelectedCollection(event.target.value)}
              >
                <option value="">Add to existing collection</option>
                {availableCollections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name}
                  </option>
                ))}
              </select>
              <button className="primary-button" onClick={handleAddCollection} type="button">
                Add
              </button>
            </div>
            <div className="create-collection-form">
              <input
                placeholder="New collection name"
                value={newCollectionName}
                onChange={(event) => setNewCollectionName(event.target.value)}
              />
              <input
                placeholder="Optional description"
                value={newCollectionDescription}
                onChange={(event) => setNewCollectionDescription(event.target.value)}
              />
              <div className="inline-form">
                <input
                  type="color"
                  className="color-input"
                  value={newCollectionColor}
                  onChange={(event) => setNewCollectionColor(event.target.value)}
                />
                <button className="secondary-button" onClick={handleCreateCollection} type="button">
                  Create collection
                </button>
              </div>
            </div>
          </section>

          <section className="detail-section">
            <div className="panel-header">
              <h3>Manual associations</h3>
            </div>
            {note.manual_links?.length ? (
              <div className="related-list">
                {note.manual_links.map((link) => (
                  <div key={link.id} className="related-card">
                    <div>
                      <strong>{link.title || "Untitled note"}</strong>
                      <p>{link.folder}</p>
                    </div>
                    <button className="ghost-button" onClick={() => onDeleteLink(link.id)} type="button">
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                Use the “Link this note” button in the results column to pin a relationship.
              </p>
            )}
          </section>

          <section className="detail-section">
            <div className="panel-header">
              <h3>Suggested related notes</h3>
              <span className="muted">Based on semantic similarity</span>
            </div>
            <div className="related-list">
              {related.length === 0 ? (
                <p className="muted">Related note suggestions will appear after embeddings are generated.</p>
              ) : null}
              {related.map((item) => (
                <div key={item.id} className="related-card">
                  <div>
                    <strong>{item.title || "Untitled note"}</strong>
                    <p>{item.folder}</p>
                  </div>
                  <span className="similarity-pill">
                    {Math.round((item.semantic_score || item.score || 0) * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
