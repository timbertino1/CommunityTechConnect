// Keyword search for the event filters (T113; FR-037): every word of the query must appear in
// the event's text (title, organizer and summary, from its data-search attribute), ignoring case
// and accents.

export const MAX_QUERY = 100;

export function normalize(text) {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function matches(text, query) {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = normalize(text);
  return words.every((word) => haystack.includes(word));
}
