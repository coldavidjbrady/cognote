import { startTransition, useEffect, useMemo, useRef, useState, useDeferredValue } from "react";
import NoteDetail from "./components/NoteDetail";
import SearchResults from "./components/SearchResults";
import Sidebar from "./components/Sidebar";
import { formatDateTime } from "./lib/date";
import {
  addNoteToCollection,
  createCollection,
  createNoteLink,
  deleteNoteLink,
  deleteOpenAIKey,
  getAppSettings,
  getCollections,
  getJobStatus,
  getNote,
  getOverview,
  getRelatedNotes,
  listNotes,
  queryAssistant,
  removeNoteFromCollection,
  searchNotes,
  startSetupJob,
  startSyncJob,
  updateOpenAIKey,
} from "./lib/api";

const SEARCH_MODES = [
  { id: "hybrid", label: "Hybrid" },
  { id: "keyword", label: "Keyword" },
  { id: "semantic", label: "Semantic" },
];
const NOTE_PAGE_SIZE = 60;

function SetupExperience({
  settings,
  overview,
  jobStatus,
  setupOptions,
  apiKeyDraft,
  onApiKeyDraftChange,
  onToggleSetupOption,
  onStartSetup,
  onSaveKey,
  isSavingKey,
}) {
  const isRunning = jobStatus?.status === "running";
  const setupCounts = jobStatus?.import_summary || null;
  const exportProgress = jobStatus?.export_progress || null;
  const importProgress = jobStatus?.import_progress || null;
  const semanticNeedsKey =
    setupOptions.enableSemantic &&
    !settings?.openai_key_configured &&
    settings?.can_manage_openai_key;

  let setupStatusDetail = null;
  if (isRunning && jobStatus?.phase === "exporting_notes") {
    const notesExported = exportProgress?.notes_exported || 0;
    const foldersTotal = exportProgress?.folders_total || null;
    const foldersCompleted = exportProgress?.folders_completed || 0;
    const currentFolder = exportProgress?.current_folder || "";
    if (notesExported > 0) {
      setupStatusDetail = `Exported ${notesExported} notes so far`;
    } else if (foldersTotal && currentFolder) {
      setupStatusDetail = `Scanning folder ${Math.min(foldersCompleted + 1, foldersTotal)} of ${foldersTotal}: ${currentFolder}`;
    } else {
      setupStatusDetail = "Scanning Apple Notes for folders and note content";
    }
  } else if (isRunning && jobStatus?.phase === "importing_database") {
    const notesImported = importProgress?.notes_imported || 0;
    setupStatusDetail =
      notesImported > 0
        ? `Imported ${notesImported} notes into the local library so far`
        : "Importing exported notes into the local library";
  } else if (overview?.total_notes) {
    setupStatusDetail = `Library currently contains ${overview.total_notes} notes`;
  }

  return (
    <main className="setup-shell">
      <section className="setup-card setup-card--primary">
        <p className="eyebrow">First launch</p>
        <h2>Build your Apple Notes library</h2>
        <p className="setup-copy">
          Cognote will export notes from Apple Notes, save a local snapshot, build the SQLite
          library, and prepare semantic search if an OpenAI key is available.
        </p>

        <div className="setup-options">
          <label className="setup-toggle">
            <input
              type="checkbox"
              checked={setupOptions.enableSemantic}
              onChange={() => onToggleSetupOption("enableSemantic")}
            />
            <span>Enable semantic search during setup</span>
          </label>
          <label className="setup-toggle">
            <input
              type="checkbox"
              checked={setupOptions.skipXlsx}
              onChange={() => onToggleSetupOption("skipXlsx")}
            />
            <span>Skip Excel export for a lighter first run</span>
          </label>
          <label className="setup-toggle">
            <input
              type="checkbox"
              checked={setupOptions.resumeExport}
              onChange={() => onToggleSetupOption("resumeExport")}
            />
            <span>Resume from the prior export state if one exists</span>
          </label>
        </div>

        <div className="setup-note-grid">
          <div className="setup-note-card">
            <strong>Library target</strong>
            <p className="muted">
              {settings?.packaged_mode
                ? "Data will live under Application Support on this Mac."
                : "Developer mode is active, so your current local database path stays in charge."}
            </p>
          </div>
          <div className="setup-note-card">
            <strong>Current semantic status</strong>
            <p className="muted">
              {settings?.openai_key_configured
                ? `Ready via ${settings.openai_key_source}.`
                : "No OpenAI key is stored yet."}
            </p>
          </div>
        </div>

        {semanticNeedsKey ? (
          <div className="settings-form">
            <label className="settings-label" htmlFor="setup-openai-key">
              OpenAI API key
            </label>
            <input
              id="setup-openai-key"
              className="search-input"
              type="password"
              placeholder="Paste the OpenAI API key you want stored in Keychain"
              value={apiKeyDraft}
              onChange={(event) => onApiKeyDraftChange(event.target.value)}
            />
            <div className="settings-actions">
              <button
                className="secondary-button"
                type="button"
                onClick={onSaveKey}
                disabled={isSavingKey || !apiKeyDraft.trim()}
              >
                {isSavingKey ? "Saving..." : "Save key now"}
              </button>
              <span className="muted">Stored locally in macOS Keychain for future launches.</span>
            </div>
          </div>
        ) : null}

        <div className="setup-actions">
          <button className="primary-button" onClick={onStartSetup} type="button" disabled={isRunning}>
            {isRunning ? "Importing notes..." : "Import Apple Notes and build library"}
          </button>
          <span className="muted">
            Apple Notes automation permission may appear during the export step.
          </span>
        </div>
      </section>

      <section className="setup-card setup-card--status">
        <div className="panel-header">
          <h3>Setup status</h3>
          <span className={`status-pill ${jobStatus?.status === "failed" ? "archived" : "syncing"}`}>
            {jobStatus?.phase || "idle"}
          </span>
        </div>

        <div className="setup-status-block">
          <strong>{jobStatus?.message || "Ready to start setup."}</strong>
          {setupStatusDetail ? <p className="muted">{setupStatusDetail}</p> : null}
          {jobStatus?.error ? <p className="sync-error">{jobStatus.error}</p> : null}
          {jobStatus?.status === "failed" && jobStatus?.log_path ? (
            <p className="muted">Diagnostic log saved to: {jobStatus.log_path}</p>
          ) : null}
          {jobStatus?.import_error_log_path ? (
            <p className="muted">Skipped-note log saved to: {jobStatus.import_error_log_path}</p>
          ) : null}
          {setupCounts ? (
            <div className="sync-metrics">
              <span>{setupCounts.imported} imported</span>
              <span>{setupCounts.changed} changed</span>
              <span>{setupCounts.archived} archived</span>
              <span>{setupCounts.embedded} embedded</span>
              <span>{setupCounts.failed || 0} skipped</span>
            </div>
          ) : null}
          <p className="muted">Latest activity: {formatDateTime(jobStatus?.finished_at || jobStatus?.started_at)}</p>
        </div>
      </section>
    </main>
  );
}

function SettingsSheet({
  settings,
  jobStatus,
  apiKeyDraft,
  onApiKeyDraftChange,
  onSaveKey,
  onRemoveKey,
  onClose,
  isSavingKey,
}) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section
        className="settings-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Cognote settings"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel-header">
          <div>
            <p className="eyebrow">Settings</p>
            <h2>Semantic search and sync</h2>
          </div>
          <button className="ghost-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="settings-summary">
          <div className="settings-summary-card">
            <strong>Runtime</strong>
            <p className="muted">{settings?.packaged_mode ? "Packaged app" : "Developer mode"}</p>
          </div>
          <div className="settings-summary-card">
            <strong>Semantic search</strong>
            <p className="muted">
              {settings?.semantic_search_enabled
                ? `Enabled via ${settings.openai_key_source}`
                : "Not active right now"}
            </p>
          </div>
          <div className="settings-summary-card">
            <strong>Last sync</strong>
            <p className="muted">{formatDateTime(jobStatus?.finished_at || jobStatus?.started_at)}</p>
          </div>
        </div>

        {settings?.can_manage_openai_key ? (
          <div className="settings-form">
            <label className="settings-label" htmlFor="settings-openai-key">
              OpenAI API key
            </label>
            <input
              id="settings-openai-key"
              className="search-input"
              type="password"
              placeholder={
                settings?.openai_key_configured
                  ? "Replace the saved Keychain entry"
                  : "Paste a key to enable semantic search"
              }
              value={apiKeyDraft}
              onChange={(event) => onApiKeyDraftChange(event.target.value)}
            />
            <div className="settings-actions">
              <button
                className="primary-button"
                type="button"
                onClick={onSaveKey}
                disabled={isSavingKey || !apiKeyDraft.trim()}
              >
                {isSavingKey ? "Saving..." : settings?.openai_key_configured ? "Replace key" : "Save key"}
              </button>
              <button
                className="ghost-button"
                type="button"
                onClick={onRemoveKey}
                disabled={isSavingKey || !settings?.openai_key_configured}
              >
                Remove key
              </button>
            </div>
          </div>
        ) : (
          <div className="settings-form">
            <strong>OpenAI key management</strong>
            <p className="muted">
              {settings?.packaged_mode
                ? "Keychain access is unavailable on this system."
                : "Developer mode reads OPENAI_API_KEY from your environment."}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

export default function App() {
  const [overview, setOverview] = useState(null);
  const [settings, setSettings] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [collections, setCollections] = useState([]);
  const [searchText, setSearchText] = useState("");
  const deferredSearch = useDeferredValue(searchText);
  const [searchMode, setSearchMode] = useState("hybrid");
  const [selectedCollectionId, setSelectedCollectionId] = useState(null);
  const [results, setResults] = useState([]);
  const [hasMoreResults, setHasMoreResults] = useState(false);
  const [nextResultsOffset, setNextResultsOffset] = useState(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [selectedNoteId, setSelectedNoteId] = useState(null);
  const [selectedNote, setSelectedNote] = useState(null);
  const [relatedNotes, setRelatedNotes] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [lastSearchText, setLastSearchText] = useState("");
  const [showAllNotes, setShowAllNotes] = useState(false);
  const [showArchivedOnly, setShowArchivedOnly] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [assistantResetKey, setAssistantResetKey] = useState(0);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [isSavingKey, setIsSavingKey] = useState(false);
  const [setupOptions, setSetupOptions] = useState({
    enableSemantic: true,
    skipXlsx: true,
    resumeExport: false,
  });
  const previousSearchRef = useRef("");
  const previousAssistantResetSignatureRef = useRef("");
  const previousJobStatusRef = useRef(null);
  const activeSearch = deferredSearch.trim();

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedCollectionId) || null,
    [collections, selectedCollectionId],
  );

  const setupRequired = Boolean(settings?.packaged_mode && overview && overview.total_notes === 0);
  const jobRunning = jobStatus?.status === "running";

  async function refreshSidebarData() {
    const [overviewPayload, collectionsPayload] = await Promise.all([getOverview(), getCollections()]);
    setOverview(overviewPayload);
    setCollections(collectionsPayload.collections || []);
  }

  async function refreshRuntimeData() {
    const [settingsPayload, jobPayload] = await Promise.all([getAppSettings(), getJobStatus()]);
    setSettings(settingsPayload);
    setJobStatus(jobPayload);
    return { settingsPayload, jobPayload };
  }

  async function refreshNoteDetail(noteId) {
    if (!noteId) {
      return;
    }
    const [notePayload, relatedPayload] = await Promise.all([
      getNote(noteId),
      getRelatedNotes(noteId),
    ]);
    setSelectedNote(notePayload);
    setRelatedNotes(relatedPayload.results || []);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([refreshSidebarData(), refreshRuntimeData()]).catch((error) => {
      if (!cancelled) {
        setErrorMessage(error.message);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const previousSearch = previousSearchRef.current;
    if (!activeSearch && previousSearch) {
      setSelectedNoteId(null);
      setSelectedNote(null);
      setRelatedNotes([]);
    }
    previousSearchRef.current = activeSearch;
  }, [activeSearch]);

  useEffect(() => {
    if (!activeSearch && !showAllNotes) {
      setIsSearching(false);
      setErrorMessage("");
      setHasMoreResults(false);
      setNextResultsOffset(0);
      setIsLoadingMore(false);
      if (!lastSearchText) {
        setResults([]);
      }
      return;
    }

    let cancelled = false;
    const searchSignature = JSON.stringify({
      activeSearch,
      searchMode,
      selectedCollectionId,
      showAllNotes,
      showArchivedOnly,
    });

    if (previousAssistantResetSignatureRef.current !== searchSignature) {
      previousAssistantResetSignatureRef.current = searchSignature;
      setAssistantResetKey((value) => value + 1);
    }

    setIsSearching(true);
    setErrorMessage("");

    const request = showAllNotes
      ? listNotes({
          collectionId: selectedCollectionId,
          archivedOnly: showArchivedOnly,
          limit: NOTE_PAGE_SIZE,
          offset: 0,
        })
      : searchNotes({
          query: deferredSearch,
          mode: searchMode,
          collectionId: selectedCollectionId,
          archivedOnly: showArchivedOnly,
        });

    request
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const nextResults = payload.results || [];
        setResults(nextResults);
        setHasMoreResults(Boolean(payload.has_more));
        setNextResultsOffset(payload.next_offset || 0);
        setIsLoadingMore(false);
        if (!showAllNotes) {
          setLastSearchText(activeSearch);
        } else {
          setLastSearchText("");
        }

        if (!nextResults.length) {
          setSelectedNoteId(null);
          setSelectedNote(null);
          setRelatedNotes([]);
          return;
        }

        const existing = nextResults.some((item) => item.id === selectedNoteId);
        if (!existing) {
          if (showAllNotes) {
            setSelectedNoteId(null);
            setSelectedNote(null);
            setRelatedNotes([]);
            return;
          }

          startTransition(() => {
            setSelectedNoteId(nextResults[0].id);
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(error.message);
          setResults([]);
          setHasMoreResults(false);
          setNextResultsOffset(0);
          setIsLoadingMore(false);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsSearching(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    deferredSearch,
    searchMode,
    selectedCollectionId,
    selectedNoteId,
    activeSearch,
    showAllNotes,
    showArchivedOnly,
    refreshNonce,
  ]);

  useEffect(() => {
    if (!selectedNoteId) {
      return;
    }
    refreshNoteDetail(selectedNoteId).catch((error) => {
      setErrorMessage(error.message);
    });
  }, [selectedNoteId]);

  useEffect(() => {
    if (!jobRunning) {
      return undefined;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const nextStatus = await getJobStatus();
        if (!cancelled) {
          setJobStatus(nextStatus);
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(error.message);
        }
      }
    };

    const intervalId = window.setInterval(() => {
      poll();
    }, 2000);
    poll();

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [jobRunning]);

  useEffect(() => {
    const previousStatus = previousJobStatusRef.current;
    if (previousStatus === "running" && jobStatus?.status && jobStatus.status !== "running") {
      Promise.all([refreshSidebarData(), refreshRuntimeData()])
        .then(() => {
          setRefreshNonce((value) => value + 1);
        })
        .catch((error) => {
          setErrorMessage(error.message);
        });
    }
    previousJobStatusRef.current = jobStatus?.status || null;
  }, [jobStatus?.status]);

  useEffect(() => {
    if (searchMode === "semantic" && settings && !settings.semantic_search_enabled) {
      setSearchMode("hybrid");
    }
  }, [searchMode, settings]);

  async function handleCreateCollection(payload) {
    await createCollection(payload);
    await refreshSidebarData();
    if (selectedNoteId) {
      await refreshNoteDetail(selectedNoteId);
    }
  }

  async function handleAddToCollection(collectionId, noteId) {
    await addNoteToCollection(collectionId, noteId);
    await refreshSidebarData();
    await refreshNoteDetail(noteId);
  }

  async function handleRemoveFromCollection(collectionId, noteId) {
    await removeNoteFromCollection(collectionId, noteId);
    await refreshSidebarData();
    await refreshNoteDetail(noteId);
  }

  async function handleAssociateNote(targetNoteId) {
    if (!selectedNoteId || selectedNoteId === targetNoteId) {
      return;
    }
    await createNoteLink({
      source_note_id: selectedNoteId,
      target_note_id: targetNoteId,
      relationship_type: "related",
      note: "",
    });
    await refreshNoteDetail(selectedNoteId);
  }

  async function handleDeleteLink(linkId) {
    await deleteNoteLink(linkId);
    if (selectedNoteId) {
      await refreshNoteDetail(selectedNoteId);
    }
  }

  async function handleLoadMoreResults() {
    if (!showAllNotes || !hasMoreResults || isLoadingMore) {
      return;
    }
    setIsLoadingMore(true);
    setErrorMessage("");
    try {
      const payload = await listNotes({
        collectionId: selectedCollectionId,
        archivedOnly: showArchivedOnly,
        limit: NOTE_PAGE_SIZE,
        offset: nextResultsOffset,
      });
      const additionalResults = payload.results || [];
      setResults((current) => [...current, ...additionalResults]);
      setHasMoreResults(Boolean(payload.has_more));
      setNextResultsOffset(payload.next_offset || 0);
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setIsLoadingMore(false);
    }
  }

  function handleSearchChange(value) {
    setSearchText(value);
    if (value.trim()) {
      setShowAllNotes(false);
    }
  }

  function handleShowAllNotes() {
    setSearchText("");
    setLastSearchText("");
    setShowAllNotes(true);
    setSelectedCollectionId(null);
    setSelectedNoteId(null);
    setSelectedNote(null);
    setRelatedNotes([]);
  }

  function handleSelectCollection(collectionId) {
    setSelectedCollectionId(collectionId);
    setShowAllNotes(true);
    setSelectedNoteId(null);
    setSelectedNote(null);
    setRelatedNotes([]);
  }

  function handleToggleArchiveMode() {
    const nextValue = !showArchivedOnly;
    setShowArchivedOnly(nextValue);
    setSearchText("");
    setLastSearchText("");
    setShowAllNotes(nextValue);
    setSelectedCollectionId(null);
    setSelectedNoteId(null);
    setSelectedNote(null);
    setRelatedNotes([]);
  }

  function handleToggleSetupOption(optionKey) {
    setSetupOptions((current) => ({
      ...current,
      [optionKey]: !current[optionKey],
    }));
  }

  async function persistOpenAIKey(value) {
    setIsSavingKey(true);
    try {
      const payload = await updateOpenAIKey(value);
      setSettings(payload);
      await refreshSidebarData();
      setApiKeyDraft("");
      return payload;
    } finally {
      setIsSavingKey(false);
    }
  }

  async function handleSaveOpenAIKey() {
    setErrorMessage("");
    try {
      await persistOpenAIKey(apiKeyDraft.trim());
    } catch (error) {
      setErrorMessage(error.message);
    }
  }

  async function handleRemoveOpenAIKey() {
    setErrorMessage("");
    setIsSavingKey(true);
    try {
      const payload = await deleteOpenAIKey();
      setSettings(payload);
      await refreshSidebarData();
      if (searchMode === "semantic") {
        setSearchMode("hybrid");
      }
      setApiKeyDraft("");
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setIsSavingKey(false);
    }
  }

  async function handleStartSetup() {
    setErrorMessage("");
    try {
      let nextSettings = settings;
      if (setupOptions.enableSemantic && !nextSettings?.openai_key_configured) {
        if (nextSettings?.can_manage_openai_key && apiKeyDraft.trim()) {
          nextSettings = await persistOpenAIKey(apiKeyDraft.trim());
        }
        if (!nextSettings?.openai_key_configured) {
          throw new Error("Enter your OpenAI key or turn semantic search off before setup.");
        }
      }

      const payload = await startSetupJob({
        skip_embeddings: !setupOptions.enableSemantic || !nextSettings?.openai_key_configured,
        skip_xlsx: setupOptions.skipXlsx,
        resume_export: setupOptions.resumeExport,
      });
      setJobStatus(payload);
    } catch (error) {
      setErrorMessage(error.message);
    }
  }

  async function handleStartSync() {
    setErrorMessage("");
    try {
      const payload = await startSyncJob({
        skip_embeddings: !settings?.openai_key_configured,
      });
      setJobStatus(payload);
    } catch (error) {
      setErrorMessage(error.message);
    }
  }

  return (
    <div className="app-shell">
      <div className="background-orb orb-a" />
      <div className="background-orb orb-b" />

      <header className="topbar">
        <div className="topbar-copy">
          <h1 className="topbar-title">Cognote - Your Natural Language Notes Browser</h1>
          <p className="topbar-subtitle">
            {showArchivedOnly
              ? "Explore archived notes without cluttering the active library"
              : "Find patterns across your Apple Notes archive"}
          </p>
        </div>

        <div className="search-controls">
          <input
            className="search-input"
            type="search"
            placeholder={
              showArchivedOnly
                ? "Search archived recipes, travel plans, ideas, and older notes..."
                : "Search recipes, lab results, ideas, meeting notes..."
            }
            value={searchText}
            onChange={(event) => handleSearchChange(event.target.value)}
          />
          <div className="mode-switcher">
            {SEARCH_MODES.map((mode) => (
              <button
                key={mode.id}
                className={`mode-pill ${searchMode === mode.id ? "active" : ""}`}
                onClick={() => setSearchMode(mode.id)}
                type="button"
                disabled={mode.id === "semantic" && settings && !settings.semantic_search_enabled}
              >
                {mode.label}
              </button>
            ))}
            <button
              className={`ghost-button ${showAllNotes && !activeSearch ? "active" : ""}`}
              onClick={handleShowAllNotes}
              type="button"
            >
              Show all notes
            </button>
            <button
              className={`ghost-button ${showArchivedOnly ? "active" : ""}`}
              onClick={handleToggleArchiveMode}
              type="button"
            >
              {showArchivedOnly ? "Archive view on" : "Archive view"}
            </button>
            <button className="secondary-button" onClick={handleStartSync} type="button" disabled={jobRunning}>
              {jobRunning ? "Syncing..." : "Sync notes"}
            </button>
            <button className="ghost-button" onClick={() => setShowSettings(true)} type="button">
              Settings
            </button>
          </div>
        </div>
      </header>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}

      {jobStatus?.status === "running" && !setupRequired ? (
        <section className="sync-banner">
          <div>
            <strong>{jobStatus.message}</strong>
            <p className="muted">
              Phase: {jobStatus.phase} • Started {formatDateTime(jobStatus.started_at)}
            </p>
          </div>
        </section>
      ) : null}

      {setupRequired ? (
        <SetupExperience
          settings={settings}
          overview={overview}
          jobStatus={jobStatus}
          setupOptions={setupOptions}
          apiKeyDraft={apiKeyDraft}
          onApiKeyDraftChange={setApiKeyDraft}
          onToggleSetupOption={handleToggleSetupOption}
          onStartSetup={handleStartSetup}
          onSaveKey={handleSaveOpenAIKey}
          isSavingKey={isSavingKey}
        />
      ) : (
        <main className="workspace-grid">
          <Sidebar
            overview={overview}
            settings={settings}
            jobStatus={jobStatus}
            collections={collections}
            selectedCollectionId={selectedCollectionId}
            onSelectCollection={handleSelectCollection}
            onShowAllNotes={handleShowAllNotes}
            showAllNotes={showAllNotes}
            archiveMode={showArchivedOnly}
          />

          <SearchResults
            results={results}
            selectedNoteId={selectedNoteId}
            onSelectNote={(noteId) => startTransition(() => setSelectedNoteId(noteId))}
            onAssociateNote={handleAssociateNote}
          activeQuery={deferredSearch}
          lastSearchText={lastSearchText}
          showAllNotes={showAllNotes}
          isLoading={isSearching}
          selectedCollection={selectedCollection}
          archiveMode={showArchivedOnly}
          hasMoreResults={showAllNotes && hasMoreResults}
          isLoadingMore={isLoadingMore}
          onLoadMore={handleLoadMoreResults}
        />

          <NoteDetail
            note={selectedNote}
            related={relatedNotes}
            allCollections={collections}
            assistantEnabled={Boolean(overview?.openai_enabled)}
            assistantResetKey={assistantResetKey}
            onAskAssistant={queryAssistant}
            onAddToCollection={handleAddToCollection}
            onRemoveFromCollection={handleRemoveFromCollection}
            onCreateCollection={handleCreateCollection}
            onDeleteLink={handleDeleteLink}
          />
        </main>
      )}

      {showSettings ? (
        <SettingsSheet
          settings={settings}
          jobStatus={jobStatus}
          apiKeyDraft={apiKeyDraft}
          onApiKeyDraftChange={setApiKeyDraft}
          onSaveKey={handleSaveOpenAIKey}
          onRemoveKey={handleRemoveOpenAIKey}
          onClose={() => setShowSettings(false)}
          isSavingKey={isSavingKey}
        />
      ) : null}
    </div>
  );
}
