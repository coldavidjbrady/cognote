import { useMemo, useState } from "react";
import { formatCollectionCount, formatNoteDate } from "../lib/date";

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

export default function NoteDetail({
  note,
  related,
  allCollections,
  onAddToCollection,
  onRemoveFromCollection,
  onCreateCollection,
  onDeleteLink,
}) {
  const [selectedCollection, setSelectedCollection] = useState("");
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionDescription, setNewCollectionDescription] = useState("");
  const [newCollectionColor, setNewCollectionColor] = useState("#315c4a");

  if (!note) {
    return (
      <section className="detail-panel detail-panel--empty">
        <div className="empty-state">
          <h2>Select a note</h2>
          <p>Pick a result to open the reader view and inspect related material.</p>
        </div>
      </section>
    );
  }

  const collectionIds = new Set((note.collections || []).map((collection) => collection.id));
  const availableCollections = allCollections.filter(
    (collection) => !collectionIds.has(collection.id),
  );

  const handleAddCollection = () => {
    if (!selectedCollection) {
      return;
    }
    onAddToCollection(Number(selectedCollection), note.id);
    setSelectedCollection("");
  };

  const handleCreateCollection = () => {
    if (!newCollectionName.trim()) {
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

  return (
    <section className="detail-panel">
      <header className="detail-header">
        <div>
          <p className="eyebrow">{note.folder}</p>
          <h2>{note.title || "Untitled note"}</h2>
          <div className="meta-row">
            <span>{formatNoteDate(note)}</span>
            <span>{note.word_count} words</span>
            <span>{note.char_count} characters</span>
          </div>
        </div>
      </header>

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

      <section className="detail-section reading-surface">
        <div className="panel-header">
          <h3>Reading view</h3>
          <span className="muted">{note.account}</span>
        </div>
        <NoteParagraphs text={note.body_text} />
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
            Use the “Associate with open note” button in the results column to pin a relationship.
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
    </section>
  );
}
