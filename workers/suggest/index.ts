/**
 * Suggestion endpoint: POST /suggest from the site's /suggest/ form (T131; contracts/workers.md
 * section 1, FR-022).
 *
 * In order: the Origin must be the site's; the body must be at most 4 KB; Turnstile must pass
 * (verified server-side, the only outbound request); at most 5 suggestions an hour per salted
 * hash of the client IP; the URL must be a public-looking https address. A valid suggestion is
 * stored in KV for 30 days for the discover-sources workflow to evaluate. The note is private:
 * cut to 280 characters with e-mail addresses and phone numbers removed, and kept only in KV.
 * Responses are neutral and never echo what was sent. Logs carry the outcome and, for a refusal,
 * which check failed (with Turnstile's own error codes), never anything the visitor sent.
 */

import { KEY_PREFIX, MAX_BODY_BYTES, MAX_URL_CHARS, MAX_NOTE_CHARS, RATE_LIMIT_PER_HOUR, TTL_SECONDS } from "./limits";

export interface Env {
  SUGGESTIONS: KVNamespace;
  TURNSTILE_SECRET: string;
  IP_HASH_SALT: string;
  /** The site's origin, e.g. https://netechconnect.pages.dev; several may be comma-separated. */
  SITE_ORIGIN: string;
}

const RATE_TTL_SECONDS = 60 * 60;
const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

// Hosts that only make sense on a private network.
const PRIVATE_SUFFIXES = [".local", ".internal", ".lan", ".localhost", ".home.arpa", ".intranet"];
const EMAIL = /[^\s@<>()"']+@[^\s@<>()"']+\.[^\s@<>()"']+/g;
// A run of digits and separators with at least 7 digits: phone numbers (and, harmlessly, dates).
const PHONE_LIKE = /\+?\(?\d[\d\s().\-/]{5,}\d/g;

type Outcome = "received" | "forbidden" | "invalid" | "rate_limited" | "not_found" | "method_not_allowed";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/suggest") {
      return reply(404, "not_found");
    }
    const origin = allowedOrigin(request.headers.get("origin"), env.SITE_ORIGIN);
    if (request.method === "OPTIONS") {
      return origin ? preflight(origin) : reply(403, "forbidden", null, "origin");
    }
    if (request.method !== "POST") {
      return reply(405, "method_not_allowed", origin);
    }
    if (!origin) {
      return reply(403, "forbidden", null, "origin");
    }

    const fields = await readFields(request);
    if (!fields) {
      return reply(400, "invalid", origin, "body");
    }
    const ip = request.headers.get("cf-connecting-ip") ?? "unknown";
    const token = fields.get("cf-turnstile-response") ?? "";
    if (!token) {
      return reply(400, "invalid", origin, "no_token");
    }
    const turnstile = await verifyTurnstile(token, ip, env.TURNSTILE_SECRET);
    if (turnstile !== "ok") {
      return reply(400, "invalid", origin, `turnstile:${turnstile}`);
    }
    if (!(await withinRateLimit(ip, env))) {
      return reply(429, "rate_limited", origin);
    }
    const suggested = publicHttpsUrl(fields.get("url") ?? "");
    if (!suggested) {
      return reply(400, "invalid", origin, "url");
    }

    const record = { url: suggested, note: scrubNote(fields.get("note") ?? ""), received_at: new Date().toISOString() };
    await env.SUGGESTIONS.put(`${KEY_PREFIX}${crypto.randomUUID()}`, JSON.stringify(record), {
      expirationTtl: TTL_SECONDS,
    });
    return reply(202, "received", origin);
  },
} satisfies ExportedHandler<Env>;

function allowedOrigin(origin: string | null, configured: string): string | null {
  if (!origin) {
    return null;
  }
  const allowed = configured.split(/[\s,]+/).filter((o) => o.length > 0);
  return allowed.includes(origin) ? origin : null;
}

/** The form or JSON fields, or null when the body is too large or unreadable. */
async function readFields(request: Request): Promise<Map<string, string> | null> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) {
    return null;
  }
  const body = await request.arrayBuffer();
  if (body.byteLength > MAX_BODY_BYTES) {
    return null;
  }
  const text = new TextDecoder().decode(body);
  const fields = new Map<string, string>();
  if ((request.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return null;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value === "string") fields.set(key, value);
    }
  } else {
    for (const [key, value] of new URLSearchParams(text)) fields.set(key, value);
  }
  return fields;
}

/** "ok", or why not: Turnstile's error codes (e.g. "invalid-input-secret"), or "unreachable". */
async function verifyTurnstile(token: string, ip: string, secret: string): Promise<string> {
  const body = new URLSearchParams({ secret, response: token });
  if (ip !== "unknown") body.set("remoteip", ip);
  try {
    const response = await fetch(SITEVERIFY, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      signal: AbortSignal.timeout(5000),
    });
    const result: { success?: unknown; "error-codes"?: unknown } = await response.json();
    if (result.success === true) {
      return "ok";
    }
    const codes = Array.isArray(result["error-codes"]) ? result["error-codes"] : [];
    const safe = codes.filter((c): c is string => typeof c === "string" && /^[a-z0-9-]{1,40}$/.test(c));
    return safe.join(",") || "failed";
  } catch {
    return "unreachable";
  }
}

/** Counts this request against the IP's hourly allowance; false once it is used up. */
async function withinRateLimit(ip: string, env: Env): Promise<boolean> {
  const key = `rate:${await sha256Hex(`${env.IP_HASH_SALT}:${ip}`)}`;
  const count = Number((await env.SUGGESTIONS.get(key)) ?? "0") || 0;
  if (count >= RATE_LIMIT_PER_HOUR) {
    return false;
  }
  await env.SUGGESTIONS.put(key, String(count + 1), { expirationTtl: RATE_TTL_SECONDS });
  return true;
}

/** The URL, normalized, when it is an https address on a public-looking host; otherwise null. */
function publicHttpsUrl(value: string): string | null {
  const text = value.trim();
  if (!text || text.length > MAX_URL_CHARS) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    (url.port !== "" && url.port !== "443") ||
    !host.includes(".") ||
    host.startsWith("[") ||
    /^[\d.]+$/.test(host) ||
    /\.\d+$/.test(host) ||
    host === "localhost" ||
    PRIVATE_SUFFIXES.some((suffix) => host.endsWith(suffix))
  ) {
    return null;
  }
  const normalized = url.toString();
  return normalized.length <= MAX_URL_CHARS ? normalized : null;
}

function scrubNote(note: string): string {
  return note
    .replace(EMAIL, " ")
    .replace(PHONE_LIKE, (match) => ((match.match(/\d/g) ?? []).length >= 7 ? " " : match))
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_NOTE_CHARS);
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function preflight(origin: string): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "access-control-allow-origin": origin,
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type",
      "access-control-max-age": "86400",
      vary: "Origin",
    },
  });
}

function reply(status: number, outcome: Outcome, origin: string | null = null, reason?: string): Response {
  console.log(JSON.stringify({ event: "suggest", outcome, ...(reason ? { reason } : {}) }));
  const headers = new Headers({
    "content-type": "application/json",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    vary: "Origin",
  });
  if (origin) headers.set("access-control-allow-origin", origin);
  return new Response(JSON.stringify({ status: outcome }), { status, headers });
}
