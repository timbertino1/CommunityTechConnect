/**
 * Newsletter inbox: the Email Worker on events@<domain> (T097; contracts/workers.md section 2,
 * research R8, gate V5).
 *
 * It does as little as it can, to stay inside the free plan's CPU limit: check the envelope
 * sender against the allow-list, forward subscription confirmations to the owner, and store the
 * raw message in KV for the discovery workflow to parse later in Python. It never parses the
 * body and reads no header but the subject. Dropped mail is only counted in the logs, without
 * any address in them.
 */

export interface Env {
  NEWSLETTERS: KVNamespace;
  /** Comma- or space-separated: full addresses, or domains (which include their subdomains). */
  ALLOWED_SENDERS: string;
  /** A verified Email Routing destination address. */
  OWNER_FORWARD_ADDRESS: string;
}

export const MAX_RAW_BYTES = 1024 * 1024;
export const TTL_SECONDS = 30 * 24 * 60 * 60;

// Subjects of "click to confirm" mails. Allowed senders only, so a false match just lands a
// newsletter in the owner's inbox.
const CONFIRMATION_SUBJECT = /\b(confirm|verify|activate)\b|\bopt[- ]?in\b|subscription confirmation/i;

export default {
  async email(message, env) {
    if (!isAllowed(message.from, env.ALLOWED_SENDERS)) {
      return log("dropped", "unknown_sender");
    }
    if (CONFIRMATION_SUBJECT.test(message.headers.get("subject") ?? "")) {
      if (!env.OWNER_FORWARD_ADDRESS) {
        return log("dropped", "no_forward_address");
      }
      await message.forward(env.OWNER_FORWARD_ADDRESS);
      return log("forwarded", "confirmation");
    }
    if (message.rawSize > MAX_RAW_BYTES) {
      return log("dropped", "too_large");
    }
    const raw = await new Response(message.raw).arrayBuffer();
    if (raw.byteLength > MAX_RAW_BYTES) {
      return log("dropped", "too_large");
    }
    await env.NEWSLETTERS.put(await sha256Hex(raw), raw, { expirationTtl: TTL_SECONDS });
    log("stored", "newsletter");
  },
} satisfies ExportedHandler<Env>;

function isAllowed(sender: string, allowList: string): boolean {
  const address = sender.trim().toLowerCase();
  const at = address.lastIndexOf("@");
  if (at <= 0 || at === address.length - 1) {
    return false;
  }
  const domain = address.slice(at + 1);
  return allowList
    .toLowerCase()
    .split(/[\s,]+/)
    .filter((entry) => entry.length > 0)
    .some((entry) => {
      if (entry.startsWith("@")) {
        entry = entry.slice(1);
      } else if (entry.includes("@")) {
        return entry === address;
      }
      return domain === entry || domain.endsWith(`.${entry}`);
    });
}

async function sha256Hex(raw: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", raw);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function log(action: "dropped" | "forwarded" | "stored", reason: string): void {
  console.log(JSON.stringify({ event: "inbox", action, reason }));
}
