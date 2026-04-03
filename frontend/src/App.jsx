import { startTransition, useEffect, useMemo, useState, useDeferredValue } from "react";
import NoteDetail from "./components/NoteDetail";
import SearchResults from "./components/SearchResults";
import Sidebar from "./components/Sidebar";
import {
  addNoteToCollection,
  createCollection,
  createNoteLink,
  deleteNoteLink,
  getCollections,
  getNote,
  getOverview,
  getRelatedNotes,
  removeNoteFromCollection,
  searchNotes,
} from "./lib/api";

const SEARCH_MODES = [
  { id: "hybrid", label: "Hybrid" },
  { id: "keyword", label: "Keyword" },
  { id: "semantic", label: "Semantic" },
];

export default function App() {
  const [overview, setOverview] = useState(null);
  const [collections, setCollections] = useState([]);
  const [searchText, setSearchText] = useState("");
  const deferredSearch = useDeferredValue(searchText);
  const [searchMode, setSearchMode] = useState("hybrid");
  const [selectedCollectionId, setSelectedCollectionId] = useState(null);
  const [results, setResults] = useState([]);
  const [selectedNoteId, setSelectedNoteId] = useState(null);
  const [selectedNote, setSelectedNote] = useState(null);
  const [relatedNotes, setRelatedNotes] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedCollectionId) || null,
    [collections, selectedCollectionId],
  );

  async function refreshSidebarData() {
    const [overviewPayload, collectionsPayload] = await Promise.all([
      getOverview(),
      getCollections(),
    ]);
    setOverview(overviewPayload);
    setCollections(collectionsPayload.collections || []);
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
    refreshSidebarData().catch((error) => {
      setErrorMessage(error.message);
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setIsSearching(true);
    setErrorMessage("");

    searchNotes({
      query: deferredSearch,
      mode: searchMode,
      collectionId: selectedCollectionId,
    })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const nextResults = payload.results || [];
        setResults(nextResults);

        if (!nextResults.length) {
          setSelectedNoteId(null);
          setSelectedNote(null);
          setRelatedNotes([]);
          return;
        }

        const existing = nextResults.some((item) => item.id === selectedNoteId);
        if (!existing) {
          startTransition(() => {
            setSelectedNoteId(nextResults[0].id);
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(error.message);
          setResults([]);
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
  }, [deferredSearch, searchMode, selectedCollectionId]);

  useEffect(() => {
    if (!selectedNoteId) {
      return;
    }
    refreshNoteDetail(selectedNoteId).catch((error) => {
      setErrorMessage(error.message);
    });
  }, [selectedNoteId]);

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

  return (
    <div className="app-shell">
      <div className="background-orb orb-a" />
      <div className="background-orb orb-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Natural-language notes browser</p>
          <h1>Find patterns across your Apple Notes archive</h1>
        </div>

        <div className="search-controls">
          <input
            className="search-input"
            type="search"
            placeholder="Search recipes, lab results, ideas, meeting notes..."
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <div className="mode-switcher">
            {SEARCH_MODES.map((mode) => (
              <button
                key={mode.id}
                className={`mode-pill ${searchMode === mode.id ? "active" : ""}`}
                onClick={() => setSearchMode(mode.id)}
                type="button"
              >
                {mode.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}

      <main className="workspace-grid">
        <Sidebar
          overview={overview}
          collections={collections}
          selectedCollectionId={selectedCollectionId}
          onSelectCollection={setSelectedCollectionId}
        />

        <SearchResults
          results={results}
          selectedNoteId={selectedNoteId}
          onSelectNote={(noteId) => startTransition(() => setSelectedNoteId(noteId))}
          onAssociateNote={handleAssociateNote}
          activeQuery={deferredSearch}
          isLoading={isSearching}
          selectedCollection={selectedCollection}
        />

        <NoteDetail
          note={selectedNote}
          related={relatedNotes}
          allCollections={collections}
          onAddToCollection={handleAddToCollection}
          onRemoveFromCollection={handleRemoveFromCollection}
          onCreateCollection={handleCreateCollection}
          onDeleteLink={handleDeleteLink}
        />
      </main>
    </div>
  );
}
