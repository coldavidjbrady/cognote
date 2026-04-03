export function formatNoteDate(note) {
  if (note?.modified_at_iso) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(note.modified_at_iso));
  }
  return note?.modified_at_display || "Date unavailable";
}

export function formatCollectionCount(count) {
  return `${count} ${count === 1 ? "note" : "notes"}`;
}
