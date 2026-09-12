/* Command palette — Cmd/Ctrl+K.
 *
 * Apple-native power-user pattern (Spotlight / macOS "Go to" pickers): a fuzzy
 * jump-list over what's already on screen, fully keyboard-operable, that never
 * replaces the primary navigation — it's a faster parallel path to the same
 * destinations the nav bar already offers.
 *
 * No new backend endpoint: the worklist's own rows (`tr[data-href]` in #worklist,
 * refreshed by htmx every 5s) are read straight out of the DOM each time the
 * palette opens, so results are always what the analyst is currently looking at.
 * Static destinations (Worklist / Dashboard / Upload) are always present so the
 * palette works identically from any page, not just the worklist.
 */
(function () {
  "use strict";

  const STATIC_DESTINATIONS = [
    { title: "Worklist", hint: "Ranked queue", href: "/console" },
    { title: "Dashboard", hint: "Backlog, hazards, latency", href: "/console/dashboard" },
    { title: "Upload a report set", hint: "Add a new PDF", href: "/console/upload" },
  ];

  let root, dialog, input, list, hint;
  let items = [];
  let active = -1;
  let lastFocused = null;

  function build() {
    if (root) return;
    root = document.createElement("div");
    root.className = "cmdk-backdrop";
    root.hidden = true;

    dialog = document.createElement("div");
    dialog.className = "cmdk";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "Command palette");

    const field = document.createElement("div");
    field.className = "cmdk-field";
    field.innerHTML =
      '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">' +
      '<circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.6"/>' +
      '<path d="M11 11l3.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
      "</svg>";
    input = document.createElement("input");
    input.type = "text";
    input.className = "cmdk-input";
    input.placeholder = "Jump to a report, or Worklist / Dashboard / Upload…";
    input.setAttribute("aria-label", "Search reports and destinations");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-controls", "cmdk-list");
    input.setAttribute("aria-autocomplete", "list");
    field.appendChild(input);
    dialog.appendChild(field);

    list = document.createElement("ul");
    list.id = "cmdk-list";
    list.className = "cmdk-list";
    list.setAttribute("role", "listbox");
    dialog.appendChild(list);

    hint = document.createElement("div");
    hint.className = "cmdk-hint";
    hint.innerHTML =
      "<span><kbd>&uarr;</kbd><kbd>&darr;</kbd> select</span>" +
      "<span><kbd>&crarr;</kbd> open</span>" +
      "<span><kbd>esc</kbd> close</span>";
    dialog.appendChild(hint);

    root.appendChild(dialog);
    document.body.appendChild(root);

    root.addEventListener("mousedown", (e) => {
      if (e.target === root) close();
    });
    input.addEventListener("input", () => render(input.value));
    input.addEventListener("keydown", onKeydown);
    dialog.addEventListener("keydown", (e) => {
      // Focus never has anywhere else to go inside this dialog (only the text
      // input is a natural tab stop), so Tab is trapped by simply keeping it
      // on the input rather than letting it escape to the page behind.
      if (e.key === "Tab") { e.preventDefault(); input.focus(); }
    });
  }

  function collectReportRows() {
    const rows = document.querySelectorAll("#worklist tr[data-href]");
    return Array.from(rows).map((tr) => {
      const acn = tr.querySelector(".row-link")?.textContent.trim() || "";
      const synopsis = tr.children[2]?.textContent.trim() || "";
      const level = tr.querySelector(".sev .label")?.textContent.trim() || "";
      return {
        title: acn || "Report",
        hint: [level, synopsis].filter(Boolean).join(" · "),
        href: tr.dataset.href,
      };
    });
  }

  // A small, dependency-free subsequence fuzzy match: every character of the
  // query must appear in order in the target, not necessarily contiguously
  // (typing "acn123" should still find "ACN 1002-3..."). Tighter (contiguous,
  // case-sensitive) matches score higher so exact substrings still win.
  function score(query, target) {
    if (!query) return 0;
    const q = query.toLowerCase();
    const t = target.toLowerCase();
    if (t.includes(q)) return 100 - t.indexOf(q);
    let qi = 0;
    let s = 0;
    for (let ti = 0; ti < t.length && qi < q.length; ti++) {
      if (t[ti] === q[qi]) { s += 1; qi++; }
    }
    return qi === q.length ? s : -1;
  }

  function render(query) {
    const pool = [...STATIC_DESTINATIONS, ...collectReportRows()];
    const q = query.trim();
    items = pool
      .map((it) => ({ it, s: score(q, it.title + " " + it.hint) }))
      .filter((r) => q === "" || r.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 40)
      .map((r) => r.it);

    list.innerHTML = "";
    if (items.length === 0) {
      const li = document.createElement("li");
      li.className = "cmdk-empty";
      li.textContent = "No matches.";
      list.appendChild(li);
      active = -1;
      return;
    }
    items.forEach((it, i) => {
      const li = document.createElement("li");
      li.className = "cmdk-item";
      li.id = "cmdk-item-" + i;
      li.setAttribute("role", "option");
      li.innerHTML =
        '<span class="cmdk-item-title"></span>' +
        (it.hint ? '<span class="cmdk-item-hint"></span>' : "");
      li.querySelector(".cmdk-item-title").textContent = it.title;
      if (it.hint) li.querySelector(".cmdk-item-hint").textContent = it.hint;
      li.addEventListener("mouseenter", () => setActive(i));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); go(it); });
      list.appendChild(li);
    });
    setActive(0);
  }

  function setActive(i) {
    active = i;
    list.querySelectorAll(".cmdk-item").forEach((el, idx) => {
      el.setAttribute("aria-selected", String(idx === active));
      el.classList.toggle("is-active", idx === active);
    });
    input.setAttribute("aria-activedescendant", active >= 0 ? "cmdk-item-" + active : "");
    if (active >= 0) list.children[active]?.scrollIntoView({ block: "nearest" });
  }

  function go(it) { location.href = it.href; }

  function onKeydown(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); if (items.length) setActive((active + 1) % items.length); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); if (items.length) setActive((active - 1 + items.length) % items.length); return; }
    if (e.key === "Enter") { e.preventDefault(); if (active >= 0 && items[active]) go(items[active]); return; }
  }

  function open() {
    build();
    lastFocused = document.activeElement;
    root.hidden = false;
    input.value = "";
    render("");
    // Wait a frame so `hidden` is cleared before focus + the open transition run.
    requestAnimationFrame(() => input.focus());
    document.body.style.overflow = "hidden";
  }

  function close() {
    if (!root || root.hidden) return;
    root.hidden = true;
    document.body.style.overflow = "";
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function isOpen() { return root && !root.hidden; }

  document.addEventListener("keydown", (e) => {
    const meta = e.metaKey || e.ctrlKey;
    if (meta && e.key.toLowerCase() === "k") {
      e.preventDefault();
      isOpen() ? close() : open();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("cmdk-trigger")?.addEventListener("click", open);
  });
})();
