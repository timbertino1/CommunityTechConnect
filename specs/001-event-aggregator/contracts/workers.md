# Contract: Cloudflare Workers

Two small Workers. Neither holds GitHub credentials, and neither fetches URLs supplied by the
public. Both only write to their own Workers KV namespace; the daily discovery workflow reads
and deletes items from KV using a token scoped to those namespaces.

## 1. Suggestion endpoint — `POST https://<worker-host>/suggest`

**Request** (`application/x-www-form-urlencoded` or JSON, ≤ 4 KB):

| Field | Rules |
|---|---|
| `url` | Required. ≤ 2,048 chars. Must parse as `https://` URL with a public-looking hostname: no IP literals, no `localhost`, no single-label hosts, no `.local`/`.internal`/`.lan`, no user-info, port absent or 443 |
| `note` | Optional. ≤ 280 chars; e-mail addresses and phone numbers removed. **Private**: kept only in KV and never copied to the repository, PRs, or issues |
| `cf-turnstile-response` | Required. Verified server-side with Turnstile before anything else |

**Behavior**:

1. Reject requests with an `Origin` other than the site's origin (CSRF protection).
2. Verify Turnstile token; on failure → `400`.
3. Rate limit: ≤ 5 suggestions per hour per salted hash of the client IP (hash only, 1-hour TTL);
   over limit → `429`.
4. Validate fields as above; invalid → `400` with a neutral message (FR-022).
5. Store `{url, note, received_at}` in KV `SUGGESTIONS` under a random key, TTL 30 days.
6. Respond `202` with `{"status":"received"}`.

**Responses** never echo submitted content. CORS allows only the site origin. The form states:
"The address you suggest may become public. Notes are private, used only to evaluate your
suggestion, and deleted after 30 days. Please don't include personal information."

## 2. Newsletter inbox — Email Worker on `events@<domain>`

**Behavior**:

1. If the envelope sender's domain/address is **not** in the `ALLOWED_SENDERS` config, drop the
   message.
2. If the message looks like a subscription confirmation (configured sender + subject patterns),
   forward it to the owner's verified address and stop.
3. If raw size > 1 MiB, drop it (record a counter only).
4. Store the raw message in KV `NEWSLETTERS` under `sha256(raw)` with TTL 30 days.

No parsing beyond headers happens in the Worker (stays within free-tier CPU, R8).

## Secrets / bindings

| Worker | Bindings |
|---|---|
| suggest | `SUGGESTIONS` (KV), `TURNSTILE_SECRET` (secret), `IP_HASH_SALT` (secret), `SITE_ORIGIN` (var) |
| inbox | `NEWSLETTERS` (KV), `ALLOWED_SENDERS` (var), `OWNER_FORWARD_ADDRESS` (var, verified address) |
