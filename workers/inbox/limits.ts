// The inbox Worker's limits (contracts/workers.md section 2).
// Kept out of index.ts: the Workers runtime treats every named export of a Worker's main
// module as an entry point, and refuses to start one that exports anything but its handler.

export const MAX_RAW_BYTES = 1024 * 1024;
export const TTL_SECONDS = 30 * 24 * 60 * 60;
