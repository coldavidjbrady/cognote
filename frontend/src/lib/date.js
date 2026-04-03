export function formatDateValue(note, isoKey, displayKey) {
  if (note?.[isoKey]) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(note[isoKey]));
  }
  return note?.[displayKey] || "Date unavailable";
}

export function formatNoteDate(note) {
  return formatDateValue(note, "modified_at_iso", "modified_at_display");
}

export function formatCollectionCount(count) {
  return `${count} ${count === 1 ? "note" : "notes"}`;
}
