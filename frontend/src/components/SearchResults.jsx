import { formatDateValue, formatNoteDate } from "../lib/date";

export default function SearchResults({
  results,
  selectedNoteId,
  onSelectNote,
  onAssociateNote,
  activeQuery,
  lastSearchText,
  showAllNotes,
  isLoading,
  selectedCollection,
  archiveMode,
  hasMoreResults,
  isLoadingMore,
  onLoadMore,
}) {
  const trimmedQuery = activeQuery.trim();
  const heading = archiveMode
    ? selectedCollection
      ? `${selectedCollection.name} archive`
      : "Archived notes"
    : selectedCollection
      ? selectedCollection.name
      : showAllNotes
        ? "All notes"
        : trimmedQuery || lastSearchText || "Search notes";

  return (
    <section className="results-panel">
      <div className="panel-header sticky">
        <div>
          <p className="eyebrow">Search results</p>
          <h2>{heading}</h2>
        </div>
        <span className="result-count">
          {isLoading
            ? "Updating..."
            : `${results.length} ${archiveMode ? "archived" : "shown"}`}
        </span>
      </div>

      <div className="results-list">
        {results.length === 0 && !isLoading ? (
          <div className="empty-state">
            {archiveMode ? (
              <>
                <h3>No archived notes matched yet</h3>
                <p>Archived notes stay hidden from the main library until you open this archive view.</p>
              </>
            ) : trimmedQuery ? (
              <>
                <h3>No notes matched yet</h3>
                <p>Try a broader phrase or switch search mode to keyword or semantic.</p>
              </>
            ) : showAllNotes ? (
              <>
                <h3>No notes available yet</h3>
                <p>Import notes or clear the collection filter to browse more material.</p>
              </>
            ) : (
              <>
                <h3>Search to begin</h3>
                <p>Results will stay here after you run a search, even if you clear the query.</p>
              </>
            )}
          </div>
        ) : null}

        {results.map((result) => (
          <article
            key={result.id}
            className={`result-card ${selectedNoteId === result.id ? "selected" : ""}`}
          >
            <button
              className="result-card__body"
              onClick={() => onSelectNote(result.id)}
              type="button"
            >
              <div className="result-card__meta">
                <span className={`match-badge match-${result.match_type}`}>{result.match_type}</span>
                {result.is_archived ? (
                  <span className="status-pill archived">Archived</span>
                ) : null}
                {result.match_type === "date" ? (
                  <>
                    <span>
                      Created {formatDateValue(result, "created_at_iso", "created_at_display")}
                    </span>
                    <span>
                      Modified {formatDateValue(result, "modified_at_iso", "modified_at_display")}
                    </span>
                  </>
                ) : (
                  <span>{formatNoteDate(result)}</span>
                )}
              </div>
              <h3>{result.title || "Untitled note"}</h3>
              <p className="result-folder">{result.folder}</p>
              <p
                className="result-snippet"
                dangerouslySetInnerHTML={{ __html: result.snippet || "No preview available." }}
              />
            </button>
            {selectedNoteId && selectedNoteId !== result.id ? (
              <button
                className="link-button"
                onClick={() => onAssociateNote(result.id)}
                type="button"
              >
                Link this note
              </button>
            ) : null}
          </article>
        ))}

        {hasMoreResults ? (
          <div className="results-footer">
            <button
              className="ghost-button results-load-more"
              onClick={onLoadMore}
              type="button"
              disabled={isLoadingMore}
            >
              {isLoadingMore ? "Loading more..." : "Load more notes"}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
