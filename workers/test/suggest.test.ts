// Suggestion endpoint Worker (T130; contracts/workers.md section 1, FR-022).
// The Worker gets requests, a fake KV namespace and a stubbed fetch for Turnstile, so these run
// in plain vitest.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import suggest, {
  KEY_PREFIX,
  MAX_BODY_BYTES,
  MAX_NOTE_CHARS,
  RATE_LIMIT_PER_HOUR,
  TTL_SECONDS,
  type Env,
} from "../suggest/index";

// Test requests have no Cloudflare edge properties; the Worker reads none of them.
type IncomingRequest = Parameters<typeof suggest.fetch>[0];
const handle = (request: Request, e: Env) => suggest.fetch(request as unknown as IncomingRequest, e);

const SITE = "https://netechconnect.pages.dev";
const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

interface Stored {
  value: string;
  ttl: number | undefined;
}

function fakeKv(): { kv: KVNamespace; stored: Map<string, Stored> } {
  const stored = new Map<string, Stored>();
  const kv = {
    get: vi.fn(async (key: string) => stored.get(key)?.value ?? null),
    put: vi.fn(async (key: string, value: string, options?: KVNamespacePutOptions) => {
      stored.set(key, { value, ttl: options?.expirationTtl });
    }),
  };
  return { kv: kv as unknown as KVNamespace, stored };
}

function env(kv: KVNamespace): Env {
  return { SUGGESTIONS: kv, TURNSTILE_SECRET: "secret-xyz", IP_HASH_SALT: "pepper", SITE_ORIGIN: SITE };
}

let turnstileOk = true;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  turnstileOk = true;
  fetchMock = vi.fn(async () => Response.json({ success: turnstileOk }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function post(
  fields: Record<string, string>,
  { origin = SITE, ip = "203.0.113.7", json = false }: { origin?: string | null; ip?: string; json?: boolean } = {},
): Request {
  const headers = new Headers({ "cf-connecting-ip": ip });
  if (origin !== null) headers.set("origin", origin);
  const body = json ? JSON.stringify(fields) : new URLSearchParams(fields).toString();
  headers.set("content-type", json ? "application/json" : "application/x-www-form-urlencoded");
  return new Request("https://netc-suggest.example.workers.dev/suggest", { method: "POST", headers, body });
}

const valid = (overrides: Record<string, string> = {}) => ({
  url: "https://www.meetup.com/omaha-rust/",
  note: "They meet monthly downtown.",
  "cf-turnstile-response": "token-abc",
  ...overrides,
});

async function call(request: Request, kv = fakeKv()) {
  const response = await handle(request, env(kv.kv));
  return { response, text: await response.text(), ...kv };
}

const suggestions = (stored: Map<string, Stored>) =>
  [...stored].filter(([key]) => key.startsWith(KEY_PREFIX)).map(([, s]) => ({ ...JSON.parse(s.value), ttl: s.ttl }));

describe("a valid suggestion", () => {
  it("is accepted with 202 and stored for 30 days", async () => {
    const { response, text, stored } = await call(post(valid()));
    expect(response.status).toBe(202);
    expect(JSON.parse(text)).toEqual({ status: "received" });
    const [saved, ...rest] = suggestions(stored);
    expect(rest).toEqual([]);
    expect(saved).toMatchObject({ url: "https://www.meetup.com/omaha-rust/", note: "They meet monthly downtown.", ttl: TTL_SECONDS });
    expect(TTL_SECONDS).toBe(30 * 24 * 60 * 60);
    expect(Date.parse(saved.received_at)).not.toBeNaN();
  });

  it("is accepted as JSON too, and the note is optional", async () => {
    const { note: _ignored, ...withoutNote } = valid();
    const { response, stored } = await call(post(withoutNote, { json: true }));
    expect(response.status).toBe(202);
    expect(suggestions(stored)[0]).toMatchObject({ note: "" });
  });

  it("answers CORS only for the site", async () => {
    const { response } = await call(post(valid()));
    expect(response.headers.get("access-control-allow-origin")).toBe(SITE);
    const preflight = await handle(
      new Request("https://w.example/suggest", { method: "OPTIONS", headers: { origin: SITE, "access-control-request-method": "POST" } }),
      env(fakeKv().kv),

    );
    expect(preflight.status).toBe(204);
    expect(preflight.headers.get("access-control-allow-origin")).toBe(SITE);
    expect(preflight.headers.get("access-control-allow-methods")).toContain("POST");
  });

  it("verifies Turnstile with the secret, the token and the client IP, and fetches nothing else", async () => {
    await call(post(valid()));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(SITEVERIFY);
    const sent = new URLSearchParams(init.body as string);
    expect(sent.get("secret")).toBe("secret-xyz");
    expect(sent.get("response")).toBe("token-abc");
    expect(sent.get("remoteip")).toBe("203.0.113.7");
  });
});

describe("rejected requests", () => {
  it.each([["https://evil.example"], [null], ["http://netechconnect.pages.dev"]])("Origin %s → 403", async (origin) => {
    const { response, stored } = await call(post(valid(), { origin }));
    expect(response.status).toBe(403);
    expect(response.headers.get("access-control-allow-origin")).toBeNull();
    expect(stored.size).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a missing Turnstile token → 400 without calling Turnstile", async () => {
    const { "cf-turnstile-response": _token, ...noToken } = valid();
    const { response, stored } = await call(post(noToken));
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(stored.size).toBe(0);
  });

  it("a failed Turnstile check → 400", async () => {
    turnstileOk = false;
    const { response, stored } = await call(post(valid()));
    expect(response.status).toBe(400);
    expect(stored.size).toBe(0);
  });

  it("Turnstile being unreachable → 400, nothing stored", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network"));
    const { response, stored } = await call(post(valid()));
    expect(response.status).toBe(400);
    expect(stored.size).toBe(0);
  });

  it.each([
    ["http://www.meetup.com/omaha-rust/"],
    ["https://203.0.113.9/events"],
    ["https://[2001:db8::1]/events"],
    ["https://localhost/events"],
    ["https://intranet/events"],
    ["https://printer.local/"],
    ["https://wiki.corp.internal/"],
    ["https://nas.lan/"],
    ["https://user:pass@example.org/"],
    ["https://example.org:8443/"],
    ["ftp://example.org/"],
    ["not a url"],
    [""],
    [`https://example.org/${"a".repeat(2048)}`],
  ])("url %s → 400", async (url) => {
    const { response, stored } = await call(post(valid({ url })));
    expect(response.status).toBe(400);
    expect(suggestions(stored)).toEqual([]);
  });

  it("port 443 is fine", async () => {
    const { response } = await call(post(valid({ url: "https://example.org:443/events" })));
    expect(response.status).toBe(202);
  });

  it("a body over 4 KB → 400", async () => {
    const { response, stored } = await call(post(valid({ note: "x".repeat(MAX_BODY_BYTES) })));
    expect(response.status).toBe(400);
    expect(stored.size).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([["GET"], ["PUT"]])("%s → 405", async (method) => {
    const response = await handle(
      new Request("https://w.example/suggest", { method, headers: { origin: SITE } }),
      env(fakeKv().kv),

    );
    expect(response.status).toBe(405);
  });

  it("other paths → 404", async () => {
    const response = await handle(new Request("https://w.example/other", { method: "POST" }), env(fakeKv().kv));
    expect(response.status).toBe(404);
  });
});

describe("rate limit", () => {
  it(`the ${RATE_LIMIT_PER_HOUR + 1}th suggestion in an hour from one IP → 429; another IP is fine`, async () => {
    const kv = fakeKv();
    for (let i = 0; i < RATE_LIMIT_PER_HOUR; i++) {
      expect((await call(post(valid({ url: `https://e${i}.example.org/` })), kv)).response.status).toBe(202);
    }
    const sixth = await call(post(valid()), kv);
    expect(sixth.response.status).toBe(429);
    expect(suggestions(kv.stored)).toHaveLength(RATE_LIMIT_PER_HOUR);
    expect((await call(post(valid(), { ip: "198.51.100.4" }), kv)).response.status).toBe(202);
  });

  it("keeps only a salted hash of the IP, for an hour", async () => {
    const { stored } = await call(post(valid()));
    const counters = [...stored].filter(([key]) => !key.startsWith(KEY_PREFIX));
    expect(counters).toHaveLength(1);
    const [key, { value, ttl }] = counters[0]!;
    expect(key).not.toContain("203.0.113.7");
    expect(value).not.toContain("203.0.113.7");
    expect(key).toMatch(/^rate:[0-9a-f]{64}$/);
    expect(ttl).toBe(3600);
  });
});

describe("privacy", () => {
  it("the note is cut to 280 characters with emails and phone numbers removed", async () => {
    const note = `Ask jane.doe@example.com or call (402) 555-0142 / +1 402.555.0199. ${"y".repeat(400)}`;
    const { stored } = await call(post(valid({ note })));
    const saved = suggestions(stored)[0].note as string;
    expect(saved.length).toBeLessThanOrEqual(MAX_NOTE_CHARS);
    expect(MAX_NOTE_CHARS).toBe(280);
    expect(saved).not.toContain("jane.doe");
    expect(saved).not.toContain("example.com");
    expect(saved).not.toMatch(/555/);
    expect(saved.startsWith("Ask")).toBe(true);
  });

  it("responses never echo what was sent", async () => {
    const marker = "https://echo-marker.example.org/";
    for (const fields of [valid({ url: marker }), valid({ url: `${marker.replace("https", "http")}` })]) {
      const { text } = await call(post(fields));
      expect(text).not.toContain("echo-marker");
      expect(text).not.toContain("monthly downtown");
    }
  });
});
