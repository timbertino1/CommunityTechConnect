/**
 * Suggestion endpoint: POST /suggest from the site's /suggest/ form (T131; contracts/workers.md
 * section 1, FR-022).
 *
 * In order: the Origin must be the site's; the body must be at most 4 KB; Turnstile must pass
 * (verified server-side, the only outbound request); at most 5 suggestions an hour per salted
 * hash of the client IP; the URL must be a public-looking https address. A valid suggestion is
 * stored in KV for 30 days for the discover-sources workflow to evaluate. The note is private:
 * cut to 280 characters with e-mail addresses and phone numbers removed, and kept only in KV.
 * Responses are neutral and never echo what was sent; logs carry the outcome only.
 */

export interface Env {
  SUGGESTIONS: KVNamespace;
  TURNSTILE_SECRET: string;
  IP_HASH_SALT: string;
  /** The site's origin, e.g. https://netechconnect.pages.dev; several may be comma-separated. */
  SITE_ORIGIN: string;
}

export const KEY_PREFIX = "suggestion:";
export const MAX_BODY_BYTES = 4 * 1024;
export const MAX_URL_CHARS = 2048;
export const MAX_NOTE_CHARS = 280;
export const RATE_LIMIT_PER_HOUR = 5;
export const TTL_SECONDS = 30 * 24 * 60 * 60;
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
      return origin ? preflight(origin) : reply(403, "forbidden");
    }
    if (request.method !== "POST") {
      return reply(405, "method_not_allowed", origin);
    }
    if (!origin) {
      return reply(403, "forbidden");
    }

    const fields = await readFields(request);
    if (!fields) {
      return reply(400, "invalid", origin);
    }
    const ip = request.headers.get("cf-connecting-ip") ?? "unknown";
    const token = fields.get("cf-turnstile-response") ?? "";
    if (!token || !(await turnstilePasses(token, ip, env.TURNSTILE_SECRET))) {
      return reply(400, "invalid", origin);
    }
    if (!(await withinRateLimit(ip, env))) {
      return reply(429, "rate_limited", origin);
    }
    const suggested = publicHttpsUrl(fields.get("url") ?? "");
    if (!suggested) {
      return reply(400, "invalid", origin);
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

async function turnstilePasses(token: string, ip: string, secret: string): Promise<boolean> {
  const body = new URLSearchParams({ secret, response: token });
  if (ip !== "unknown") body.set("remoteip", ip);
  try {
    const response = await fetch(SITEVERIFY, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      signal: AbortSignal.timeout(5000),
    });
    const result: { success?: unknown } = await response.json();
    return result.success === true;
  } catch {
    return false;
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

function reply(status: number, outcome: Outcome, origin: string | null = null): Response {
  console.log(JSON.stringify({ event: "suggest", outcome }));
  const headers = new Headers({
    "content-type": "application/json",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    vary: "Origin",
  });
  if (origin) headers.set("access-control-allow-origin", origin);
  return new Response(JSON.stringify({ status: outcome }), { status, headers });
}
