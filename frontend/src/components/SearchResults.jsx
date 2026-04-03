import { formatNoteDate } from "../lib/date";

export default function SearchResults({
  results,
  selectedNoteId,
  onSelectNote,
  onAssociateNote,
  activeQuery,
  isLoading,
  selectedCollection,
}) {
  return (
    <section className="results-panel">
      <div className="panel-header sticky">
        <div>
          <p className="eyebrow">Search results</p>
          <h2>
            {selectedCollection ? selectedCollection.name : activeQuery || "Recent notes"}
          </h2>
        </div>
        <span className="result-count">
          {isLoading ? "Updating..." : `${results.length} shown`}
        </span>
      </div>

      <div className="results-list">
        {results.length === 0 && !isLoading ? (
          <div className="empty-state">
            <h3>No notes matched yet</h3>
            <p>Try a broader phrase or switch search mode to keyword or semantic.</p>
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
                <span>{formatNoteDate(result)}</span>
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
                Associate with open note
              </button>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
