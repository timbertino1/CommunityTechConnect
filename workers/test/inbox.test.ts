// Newsletter inbox Worker (T096; contracts/workers.md section 2, research R8).
// The Worker gets fake email messages and a fake KV namespace, so these run in plain vitest.

import { describe, expect, it, vi } from "vitest";

import inbox, { MAX_RAW_BYTES, TTL_SECONDS, type Env } from "../inbox/index";

const NEWSLETTER = [
  "From: Prairie Tech Weekly <weekly@news.example.com>",
  "To: events@netechconnect.example",
  "Subject: This week in Nebraska tech",
  "Message-ID: <weekly-2026-10-19@news.example.com>",
  "Content-Type: text/plain; charset=utf-8",
  "",
  "Coming up: Rust Night, Wed Nov 18 at Kiewit Luminarium, Omaha.",
  "",
].join("\r\n");

interface Stored {
  value: ArrayBuffer;
  ttl: number | undefined;
}

function fakeKv(): { kv: KVNamespace; stored: Map<string, Stored> } {
  const stored = new Map<string, Stored>();
  const kv = {
    put: vi.fn(async (key: string, value: ArrayBuffer, options?: KVNamespacePutOptions) => {
      stored.set(key, { value, ttl: options?.expirationTtl });
    }),
  };
  return { kv: kv as unknown as KVNamespace, stored };
}

function env(kv: KVNamespace, overrides: Partial<Env> = {}): Env {
  return {
    NEWSLETTERS: kv,
    ALLOWED_SENDERS: "news.example.com, digest@lists.example.org",
    OWNER_FORWARD_ADDRESS: "owner@example.net",
    ...overrides,
  };
}

function email(
  raw: string,
  { from = "bounce-123@news.example.com", subject = "This week in Nebraska tech", rawSize = -1 } = {},
) {
  const bytes = new TextEncoder().encode(raw);
  const headers = new Headers({ subject });
  const getHeader = vi.spyOn(headers, "get");
  const message = {
    from,
    to: "events@netechconnect.example",
    headers,
    raw: new Blob([bytes]).stream(),
    rawSize: rawSize >= 0 ? rawSize : bytes.byteLength,
    setReject: vi.fn(),
    forward: vi.fn(async () => ({ messageId: "fwd" })),
    reply: vi.fn(),
  };
  return { message, bytes, getHeader, asEmail: message as unknown as ForwardableEmailMessage };
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

describe("newsletter inbox", () => {
  it("drops mail from a sender not on the allow-list", async () => {
    const { kv, stored } = fakeKv();
    const { message, asEmail } = email(NEWSLETTER, { from: "someone@stranger.example" });

    await inbox.email(asEmail, env(kv));

    expect(stored.size).toBe(0);
    expect(message.forward).not.toHaveBeenCalled();
  });

  it("does not let a look-alike domain through", async () => {
    const { kv, stored } = fakeKv();
    const { asEmail } = email(NEWSLETTER, { from: "weekly@evilnews.example.com" });

    await inbox.email(asEmail, env(kv));

    expect(stored.size).toBe(0);
  });

  it("drops everything when the allow-list is empty", async () => {
    const { kv, stored } = fakeKv();
    const { asEmail } = email(NEWSLETTER);

    await inbox.email(asEmail, env(kv, { ALLOWED_SENDERS: "" }));

    expect(stored.size).toBe(0);
  });

  it("accepts an allowed address exactly and an allowed domain with its subdomains", async () => {
    for (const from of ["Digest@Lists.Example.org", "weekly@news.example.com", "a@mail.news.example.com"]) {
      const { kv, stored } = fakeKv();
      await inbox.email(email(NEWSLETTER, { from }).asEmail, env(kv));
      expect(stored.size, from).toBe(1);
    }
    const { kv, stored } = fakeKv();
    await inbox.email(email(NEWSLETTER, { from: "other@lists.example.org" }).asEmail, env(kv));
    expect(stored.size).toBe(0);
  });

  it("forwards a subscription confirmation from an allowed sender to the owner", async () => {
    const { kv, stored } = fakeKv();
    const { message, asEmail } = email(NEWSLETTER, { subject: "Please confirm your subscription" });

    await inbox.email(asEmail, env(kv));

    expect(message.forward).toHaveBeenCalledWith("owner@example.net");
    expect(stored.size).toBe(0);
  });

  it("does not forward a confirmation from an unknown sender", async () => {
    const { kv } = fakeKv();
    const { message, asEmail } = email(NEWSLETTER, {
      from: "x@stranger.example",
      subject: "Confirm your email address",
    });

    await inbox.email(asEmail, env(kv));

    expect(message.forward).not.toHaveBeenCalled();
  });

  it("drops a message over 1 MiB without reading it", async () => {
    const { kv, stored } = fakeKv();
    const { message, asEmail } = email(NEWSLETTER, { rawSize: MAX_RAW_BYTES + 1 });

    await inbox.email(asEmail, env(kv));

    expect(stored.size).toBe(0);
    expect(message.raw.locked).toBe(false);
  });

  it("stores an allowed newsletter under sha256(raw) for 30 days", async () => {
    const { kv, stored } = fakeKv();
    const { bytes, asEmail } = email(NEWSLETTER);

    await inbox.email(asEmail, env(kv));

    const key = await sha256Hex(bytes);
    expect([...stored.keys()]).toEqual([key]);
    expect(stored.get(key)?.ttl).toBe(TTL_SECONDS);
    expect(TTL_SECONDS).toBe(30 * 24 * 60 * 60);
  });

  it("stores the raw bytes as received and reads no header but the subject", async () => {
    const { kv, stored } = fakeKv();
    const broken = "Subject: x\r\nContent-Type: multipart/mixed; boundary=\"nope\"\r\n\r\n--never closed \xff";
    const { bytes, getHeader, asEmail } = email(broken);

    await inbox.email(asEmail, env(kv));

    const [entry] = [...stored.values()];
    expect(new Uint8Array(entry?.value ?? new ArrayBuffer(0))).toEqual(bytes);
    expect(new Set(getHeader.mock.calls.map(([name]) => name.toLowerCase()))).toEqual(new Set(["subject"]));
  });
});
