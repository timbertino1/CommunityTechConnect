// Event filters on the list and calendar pages (T113; FR-036-FR-038, contracts/site-urls.md).
//
// The page already holds every event; this shows the ones that match the filters in the
// address (area, cat, from, to, q), keeps the form and the address in step, announces how many
// match, and carries the filters on the links between the list and the calendar so they survive
// switching views and paging through months and weeks. Invalid values are dropped. Nothing is
// sent anywhere. Without JavaScript the form stays hidden and every event shows.

import { MAX_QUERY, matches } from "/js/search.js";

const AREAS = ["omaha", "lincoln", "other_ne", "online"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const form = document.querySelector("[data-filters]");

if (form) {
  const topics = [...form.querySelectorAll('select[name="cat"] option')].map((o) => o.value).filter(Boolean);
  let filters = parse(window.location.search, topics);
  const links = pageLinks();

  form.hidden = false;
  fill(form, filters);
  apply(filters, links);

  form.addEventListener("submit", (event) => event.preventDefault());
  form.addEventListener("change", (event) => {
    filters = update(filters, form, event.target);
    show(filters, links);
  });
  let typing = 0;
  form.querySelector('input[name="q"]').addEventListener("input", (event) => {
    window.clearTimeout(typing);
    typing = window.setTimeout(() => {
      filters = update(filters, form, event.target);
      show(filters, links);
    }, 200);
  });
}

/** The filters in a query string, with anything invalid left out. */
export function parse(search, topics) {
  const params = new URLSearchParams(search);
  const list = (name, allowed) => [
    ...new Set((params.get(name) || "").split(",").map((v) => v.trim()).filter((v) => allowed.includes(v))),
  ];
  return {
    area: list("area", AREAS),
    cat: list("cat", topics),
    from: validDate(params.get("from")),
    to: validDate(params.get("to")),
    q: (params.get("q") || "").trim().slice(0, MAX_QUERY),
  };
}

/** The query string for some filters ("" for none), commas left readable. */
export function serialize(filters) {
  const parts = [];
  for (const name of ["area", "cat"]) {
    if (filters[name].length) parts.push(`${name}=${filters[name].map(encodeURIComponent).join(",")}`);
  }
  for (const name of ["from", "to", "q"]) {
    if (filters[name]) parts.push(`${name}=${encodeURIComponent(filters[name])}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

/** Whether an event (its data-* attributes) passes the filters. */
export function keep(data, filters) {
  if (filters.area.length && !filters.area.includes(data.area)) return false;
  if (filters.cat.length && !data.cats.split(" ").some((c) => filters.cat.includes(c))) return false;
  if (filters.from && data.end < filters.from) return false; // dates overlap, so a two-day
  if (filters.to && data.start > filters.to) return false; // event counts on either day
  return matches(data.search, filters.q);
}

function validDate(value) {
  if (!value || !ISO_DATE.test(value)) return "";
  const date = new Date(`${value}T12:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : "";
}

function active(filters) {
  return Boolean(filters.area.length || filters.cat.length || filters.from || filters.to || filters.q);
}

function fill(target, filters) {
  for (const box of target.querySelectorAll('input[name="area"]')) box.checked = filters.area.includes(box.value);
  target.querySelector('select[name="cat"]').value = filters.cat[0] || "";
  target.querySelector('input[name="from"]').value = filters.from;
  target.querySelector('input[name="to"]').value = filters.to;
  target.querySelector('input[name="q"]').value = filters.q;
}

// One control changed: update only what it controls, so several topics from a shared link
// survive a change elsewhere in the form.
function update(filters, source, control) {
  const next = { ...filters };
  switch (control.name) {
    case "area":
      next.area = [...source.querySelectorAll('input[name="area"]:checked')].map((b) => b.value);
      break;
    case "cat":
      next.cat = control.value ? [control.value] : [];
      break;
    case "from":
    case "to":
      next[control.name] = validDate(control.value);
      break;
    case "q":
      next.q = control.value.trim().slice(0, MAX_QUERY);
      break;
    default:
      return filters;
  }
  return next;
}

// The links to list and calendar pages, with the address each had before filters were added.
function pageLinks() {
  return [...document.querySelectorAll("a[href]")]
    .map((a) => {
      const href = a.getAttribute("href");
      const base = a.dataset.currentMonth || href; // /calendar/ is a redirect: go to the month
      const list = href === "/";
      const calendar = href.startsWith("/calendar/");
      return list || calendar ? { a, base } : null;
    })
    .filter(Boolean);
}

function show(filters, links) {
  window.history.replaceState(null, "", `${window.location.pathname}${serialize(filters)}`);
  apply(filters, links);
}

function apply(filters, links) {
  const query = serialize(filters);
  for (const { a, base } of links) a.setAttribute("href", query ? `${base}${query}` : a.dataset.currentMonth ? "/calendar/" : base);
  const clear = form.querySelector("[data-filter-clear]");
  clear.setAttribute("href", window.location.pathname);
  clear.hidden = !active(filters);

  const shownEvents = new Set();
  const allEvents = new Set();
  for (const item of document.querySelectorAll("[data-search]")) {
    const box = item.closest("li") || item;
    const visible = keep(item.dataset, filters);
    box.hidden = !visible;
    const id = item.querySelector('a[href^="/events/"]')?.getAttribute("href");
    allEvents.add(id);
    if (visible) shownEvents.add(id);
  }
  for (const section of document.querySelectorAll("section.month")) {
    const items = [...section.querySelectorAll("[data-search]")];
    const visible = items.filter((item) => !(item.closest("li") || item).hidden).length;
    section.hidden = visible === 0;
    const count = section.querySelector(".month-count");
    if (count) {
      count.dataset.all ??= count.textContent;
      count.textContent = active(filters) ? `${visible} of ${items.length} events` : count.dataset.all;
    }
  }
  for (const cell of document.querySelectorAll("td[data-date]")) {
    const entries = cell.querySelectorAll("li[data-search]");
    cell.classList.toggle("is-filtered-empty", entries.length > 0 && !cell.querySelector("li[data-search]:not([hidden])"));
  }

  const status = document.querySelector("[data-filter-status]");
  if (!active(filters)) status.textContent = "";
  else if (shownEvents.size === 0) status.textContent = "No events match these filters.";
  else status.textContent = `Showing ${shownEvents.size} of ${allEvents.size} events.`;
}
