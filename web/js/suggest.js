// The /suggest/ form (T132; contracts/workers.md section 1): posts the address, the optional
// note and the Turnstile token to the suggestion Worker, then says what happened in neutral
// words. The Worker never echoes what was sent, and neither does this page.

export const MESSAGES = {
  received: "Thanks! We'll take a look. If it fits, its events will appear after review.",
  invalid: "That didn't go through. Check that the address starts with https:// and try again.",
  rate_limited: "That's a lot of suggestions from here this hour. Please try again later.",
  failed: "We couldn't send that just now. Please try again later.",
  not_ready: "Please wait for the spam check to finish, then try again.",
};

/** The message for a Worker response status. */
export function messageFor(status) {
  if (status === 202) return MESSAGES.received;
  if (status === 429) return MESSAGES.rate_limited;
  if (status === 400) return MESSAGES.invalid;
  return MESSAGES.failed;
}

const form = document.querySelector("[data-suggest]");
if (form) start(form);

function start(form) {
  const status = form.querySelector("[data-suggest-status]");
  const button = form.querySelector('button[type="submit"]');
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = new FormData(form);
    if (!fields.get("cf-turnstile-response")) {
      status.textContent = MESSAGES.not_ready;
      return;
    }
    button.disabled = true;
    status.textContent = "Sending…";
    let message;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(fields).toString(),
        credentials: "omit",
      });
      message = messageFor(response.status);
      if (response.status === 202) form.reset();
    } catch {
      message = MESSAGES.failed;
    }
    status.textContent = message;
    button.disabled = false;
    window.turnstile?.reset(); // a token works once
  });
}
