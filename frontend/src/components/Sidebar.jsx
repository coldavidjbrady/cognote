import { formatCollectionCount } from "../lib/date";

function StatCard({ label, value, accent }) {
  return (
    <div className="stat-card">
      <div className="stat-card__label">{label}</div>
      <div className="stat-card__value" style={{ color: accent }}>
        {value}
      </div>
    </div>
  );
}

export default function Sidebar({
  overview,
  collections,
  selectedCollectionId,
  onSelectCollection,
}) {
  return (
    <aside className="sidebar">
      <section className="sidebar-panel hero-panel">
        <p className="eyebrow">Local note intelligence</p>
        <h1>Apple Notes Search</h1>
        <p className="hero-copy">
          Search by exact phrase, by meaning, or both. Group notes into meaningful
          collections and review connected material without digging through the Notes app.
        </p>
      </section>

      <section className="sidebar-panel">
        <div className="panel-header">
          <h2>Library</h2>
          <span className={`status-pill ${overview?.openai_enabled ? "on" : "off"}`}>
            {overview?.openai_enabled ? "Semantic ready" : "Keyword mode"}
          </span>
        </div>
        <div className="stat-grid">
          <StatCard
            label="Notes"
            value={overview?.total_notes || 0}
            accent="var(--accent-forest)"
          />
          <StatCard
            label="Folders"
            value={overview?.total_folders || 0}
            accent="var(--accent-rust)"
          />
          <StatCard
            label="Embeddings"
            value={overview?.notes_with_embeddings || 0}
            accent="var(--accent-gold)"
          />
        </div>
      </section>

      <section className="sidebar-panel">
        <div className="panel-header">
          <h2>Collections</h2>
          <button
            className={`ghost-button ${selectedCollectionId === null ? "active" : ""}`}
            onClick={() => onSelectCollection(null)}
            type="button"
          >
            All notes
          </button>
        </div>
        <div className="collection-list">
          {collections.length === 0 ? (
            <p className="muted">Create collections like Health, Recipes, or Research.</p>
          ) : null}
          {collections.map((collection) => (
            <button
              key={collection.id}
              className={`collection-item ${
                selectedCollectionId === collection.id ? "selected" : ""
              }`}
              onClick={() => onSelectCollection(collection.id)}
              type="button"
            >
              <span
                className="collection-item__swatch"
                style={{ backgroundColor: collection.color }}
              />
              <span className="collection-item__content">
                <strong>{collection.name}</strong>
                <small>{formatCollectionCount(collection.note_count)}</small>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="sidebar-panel">
        <div className="panel-header">
          <h2>Top folders</h2>
        </div>
        <div className="folder-list">
          {(overview?.top_folders || []).map((folder) => (
            <div key={folder.folder} className="folder-row">
              <span>{folder.folder}</span>
              <strong>{folder.note_count}</strong>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
