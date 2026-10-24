// The suggest Worker's limits (contracts/workers.md section 1).
// Kept out of index.ts: the Workers runtime treats every named export of a Worker's main
// module as an entry point, and refuses to start one that exports anything but its handler.

export const KEY_PREFIX = "suggestion:";
export const MAX_BODY_BYTES = 4 * 1024;
export const MAX_URL_CHARS = 2048;
export const MAX_NOTE_CHARS = 280;
export const RATE_LIMIT_PER_HOUR = 5;
export const TTL_SECONDS = 30 * 24 * 60 * 60;
