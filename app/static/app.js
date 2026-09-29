// Kanki frontend: plain JavaScript, no build step.
// Model text is always inserted with textContent / value, never innerHTML.
//
// The server generates content and adds cards to the authenticated user's Anki.

"use strict";

// Languages always offered in the override dropdown. A detected language that
// is not in this list is added to the dropdown automatically.
const LANGUAGES = ["English", "Korean", "Japanese"];

const STORAGE_DECK = "kanki.lastDeck";
const STORAGE_EXAMPLES = "kanki.numExamples";
const STORAGE_LANGUAGE = "kanki.language";

const $ = (id) => document.getElementById(id);

// Current word and the user's edits for each meaning (same order as the results).
const state = {
  busy: false,
  result: null,      // response from /api/generate
  edits: [],         // editable copy of each meaning
  selected: new Set(), // indexes of checked meanings
};

// ---------------------------------------------------------------------------
// localStorage helpers (it can be unavailable, e.g. in private windows)
// ---------------------------------------------------------------------------

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function save(key, value) {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------

function showStatus(message, kind = "info") {
  const box = $("status");
  box.textContent = message;
  box.className = `status ${kind}`;
  box.hidden = false;
}

function hideStatus() {
  $("status").hidden = true;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) node.append(child);
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorText(data.detail) || `Request failed (${response.status})`);
  }
  return data;
}

// FastAPI validation errors come as a list of objects.
function errorText(detail) {
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return detail;
}

function setBusy(busy) {
  state.busy = busy;
  for (const id of ["generate-btn", "add-btn", "add-anyway-btn", "language-select", "word-input", "num-examples"]) {
    $(id).disabled = busy;
  }
  for (const field of document.querySelectorAll("#results input, #preview input, #preview textarea, #preview select")) {
    field.disabled = busy;
  }
}

// ---------------------------------------------------------------------------
// Server Anki and sync status
// ---------------------------------------------------------------------------
let syncTimer = null;
function showSync(sync) {
  const box = $("sync-status");
  const labels = {
    idle: "No sync requested yet.", queued: "Sync queued…",
    running: "Syncing with AnkiWeb…", finished: "Anki collection sync finished.",
    error: `Sync needs attention: ${sync.detail || "Check server Anki."}`,
  };
  box.textContent = labels[sync.state] || "Sync status unknown.";
  $("retry-sync-btn").hidden = sync.state !== "error";
  if (syncTimer) clearTimeout(syncTimer);
  if (sync.state === "queued" || sync.state === "running") {
    syncTimer = setTimeout(refreshSync, 2000);
  }
}
async function refreshSync() {
  try { showSync(await api("/api/sync")); }
  catch (err) { showSync({ state: "error", detail: err.message }); }
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

const info = { provider: "", model: "" };

function showModel(model) {
  const fallback = model !== info.model ? " (fallback)" : "";
  $("provider-label").textContent = `${info.provider} · ${model}${fallback}`;
}

async function loadInfo() {
  try {
    Object.assign(info, await api("/api/info"));
    showModel(info.model);
  } catch {
    $("provider-label").textContent = "provider unknown";
  }
}

async function loadDecks() {
  const select = $("deck-select");
  try {
    const decks = await api("/api/decks");
    hideStatus();
    select.replaceChildren(...decks.map((d) => el("option", { value: d, textContent: d })));
    const last = load(STORAGE_DECK);
    // Use the deck chosen last time, or the first deck if it no longer exists.
    select.value = decks.includes(last) ? last : decks[0] ?? "";
    return true;
  } catch (err) {
    showStatus(err.message, "error");
    return false;
  }
}

function initSettings() {
  const language = $("language-select");
  const storedLanguage = load(STORAGE_LANGUAGE) || "";
  const languages = [...LANGUAGES];
  if (storedLanguage && !languages.includes(storedLanguage)) languages.push(storedLanguage);
  language.replaceChildren(
    el("option", { value: "", textContent: "Auto-detect" }),
    ...languages.map((l) => el("option", { value: l, textContent: l })),
  );
  language.value = storedLanguage;
  const select = $("num-examples");
  const stored = load(STORAGE_EXAMPLES);
  select.value = ["1", "2", "3"].includes(stored) ? stored : "2";
  select.addEventListener("change", () => save(STORAGE_EXAMPLES, select.value));
}

// ---------------------------------------------------------------------------
// Step 1: generate
// ---------------------------------------------------------------------------

async function generate(word, language = null) {
  if (state.busy) return;
  setBusy(true);
  // A failed regeneration must not leave an older word available to add.
  state.result = null;
  $("results").hidden = true;
  $("preview").hidden = true;
  $("duplicate-box").hidden = true;
  showStatus(language ? `Generating in ${language}…` : "Generating…", "info");
  const generationStarted = Date.now();
  let requestId = null;
  let firstMeaningReported = false;

  function reportTiming(event) {
    if (!requestId) return;
    fetch("/api/metrics/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: requestId, event, elapsed_ms: Date.now() - generationStarted,
      }),
    }).catch(() => {}); // Metrics must never affect card generation.
  }
  try {
    const response = await fetch("/api/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word, language, num_examples: Number($("num-examples").value) }),
    });
    await readGenerationStream(response, (event) => {
      if (event.type === "start") {
        requestId = event.request_id || requestId;
        state.result = {
          word, model: event.model, detected_language: language || "",
          language_code: "", meanings: [],
        };
        state.edits = [];
        state.selected = new Set();
        $("results").hidden = true;
        $("preview").hidden = true;
        showModel(event.model);
        showStatus(event.attempt > 1 ? "Checking the response again…" : "Generating…", "info");
      } else if (event.type === "meaning") {
        if (!firstMeaningReported) {
          firstMeaningReported = true;
          reportTiming("first_meaning");
        }
        state.result.meanings.push(event.meaning);
        state.result.detected_language = event.detected_language || state.result.detected_language;
        state.result.language_code = event.language_code || state.result.language_code;
        useResult(state.result);
        showStatus(`${state.result.meanings.length} meaning(s) received · still generating…`, "info");
      } else if (event.type === "done") {
        useResult(event.result);
        reportTiming("complete");
      }
    });
    hideStatus();
  } catch (err) {
    reportTiming("error");
    state.result = null;
    state.edits = [];
    state.selected = new Set();
    $("results").hidden = true;
    $("preview").hidden = true;
    showStatus(err.message, "error");
  } finally {
    setBusy(false);
  }
}

function useResult(result) {
  state.result = result;
  showModel(result.model);
  state.edits = result.meanings.map((m) => ({
    part_of_speech: m.part_of_speech,
    definition: m.definition,
    examples: [...m.examples],
    examples_masked: [...m.examples_masked],
    synonyms: m.synonyms.join(", "),
  }));
  state.selected = new Set(result.meanings.map((_, i) => i));
  renderResults();
  setBusy(state.busy); // Newly rendered fields stay read-only until validation finishes.
}

// ---------------------------------------------------------------------------
// Step 2: language and meaning selection
// ---------------------------------------------------------------------------

function renderResults() {
  const { result } = state;

  // Language dropdown: the fixed list plus the detected language if missing.
  const langSelect = $("language-select");
  if (result.detected_language && ![...langSelect.options].some((o) => o.value === result.detected_language)) {
    langSelect.append(el("option", { value: result.detected_language, textContent: result.detected_language }));
  }
  $("detected-language").textContent = `Language: ${result.detected_language}`;

  // Meanings as checkboxes.
  const list = $("meanings");
  list.replaceChildren(...result.meanings.map((m, i) => {
    const box = el("input", { type: "checkbox", checked: state.selected.has(i) });
    box.addEventListener("change", () => {
      if (box.checked) state.selected.add(i); else state.selected.delete(i);
      renderPreview();
    });
    return el("li", {}, [
      el("label", {}, [
        box,
        el("span", { className: "pos", textContent: m.part_of_speech }),
        el("span", { textContent: m.label }),
      ]),
    ]);
  }));

  $("field-word").value = result.word;
  $("field-language").value = result.detected_language;
  $("results").hidden = false;
  renderPreview();
}

// ---------------------------------------------------------------------------
// Step 3: editable preview
// ---------------------------------------------------------------------------

// A text input or textarea bound to state.edits[i][key] (or [key][j]).
function boundField(tag, i, key, j = null) {
  const edit = state.edits[i];
  const field = el(tag, { value: j === null ? edit[key] : edit[key][j] });
  if (tag === "textarea") field.rows = 2;
  field.addEventListener("input", () => {
    if (j === null) edit[key] = field.value; else edit[key][j] = field.value;
  });
  return field;
}

function warning(text) {
  return el("span", { className: "flag", textContent: `⚠ ${text}` });
}

function renderPreview() {
  const indexes = [...state.selected].sort((a, b) => a - b);
  const container = $("meaning-editors");

  container.replaceChildren(...indexes.map((i, n) => {
    const original = state.result.meanings[i];
    const edit = state.edits[i];

    const defLabel = el("label", {}, ["Definition"]);
    if (original.definition_warning) defLabel.append(warning("contains the word"));
    defLabel.append(boundField("textarea", i, "definition"));

    const examples = edit.examples.map((_, j) => boundField("textarea", i, "examples", j));
    const masked = edit.examples_masked.map((_, j) => {
      const wrap = el("div", { className: "masked" });
      if (original.masked_flags[j]) wrap.append(warning("auto-masked, please check"));
      wrap.append(boundField("textarea", i, "examples_masked", j));
      return wrap;
    });

    return el("fieldset", { className: "meaning-editor" }, [
      el("legend", { textContent: indexes.length > 1 ? `${n + 1}. ${original.label}` : original.label }),
      el("label", {}, ["Part of speech", boundField("input", i, "part_of_speech")]),
      defLabel,
      el("div", { className: "label" }, ["Examples"]), ...examples,
      el("div", { className: "label" }, ["Examples (masked, for the reverse card)"]), ...masked,
      el("label", {}, ["Synonyms (comma-separated)", boundField("input", i, "synonyms")]),
    ]);
  }));

  $("preview").hidden = indexes.length === 0;
}

// ---------------------------------------------------------------------------
// Add to Anki
// ---------------------------------------------------------------------------

// The note as edited in the preview, in the shape /api/add expects.
function buildNoteRequest() {
  const indexes = [...state.selected].sort((a, b) => a - b);
  return {
    word: $("field-word").value.trim(),
    language: $("field-language").value.trim(),
    deck: $("deck-select").value,
    meanings: indexes.map((i) => {
      const e = state.edits[i];
      return {
        part_of_speech: e.part_of_speech,
        definition: e.definition,
        examples: e.examples,
        examples_masked: e.examples_masked,
        synonyms: e.synonyms.split(/[,、，]/).map((s) => s.trim()).filter(Boolean),
      };
    }),
  };
}

async function addToAnki(allowDuplicate = false) {
  if (state.busy || !state.result) return;
  // Anki may have been opened after this page loaded: fetch the decks again.
  if (!$("deck-select").value && !(await loadDecks())) return;

  const request = buildNoteRequest();
  if (!request.word) return showStatus("The Word field is empty.", "error");
  if (!request.deck) return showStatus("Choose a deck first.", "error");
  if (request.meanings.length === 0) return showStatus("Select at least one meaning.", "error");

  setBusy(true);
  $("duplicate-box").hidden = true;
  try {
    const result = await api(`/api/add?allow_duplicate=${allowDuplicate}`, request);
    if (result.duplicate) {
      $("duplicate-box").hidden = false;
      hideStatus();
      return;
    }
    showSync(result.sync);
    save(STORAGE_DECK, request.deck);
    showStatus(`Added “${request.word}” to ${request.deck}.`, "success");
    resetForNextWord();
  } catch (err) {
    showStatus(err.message, "error");
  } finally {
    setBusy(false);
  }
}

function resetForNextWord() {
  state.result = null;
  state.edits = [];
  state.selected = new Set();
  $("word-input").value = "";
  $("results").hidden = true;
  $("preview").hidden = true;
  $("duplicate-box").hidden = true;
  $("word-input").focus();
}

// ---------------------------------------------------------------------------
// Wire up events
// ---------------------------------------------------------------------------

$("word-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const word = $("word-input").value.trim();
  if (word) generate(word, $("language-select").value || null);
});

$("language-select").addEventListener("change", () => {
  const language = $("language-select").value;
  save(STORAGE_LANGUAGE, language);
  // Use the current input, not the previous result, if the user has typed a new word.
  const word = $("word-input").value.trim();
  if (state.result && word) generate(word, language || null);
});

$("deck-select").addEventListener("change", () => save(STORAGE_DECK, $("deck-select").value));
$("add-btn").addEventListener("click", () => addToAnki(false));
$("add-anyway-btn").addEventListener("click", () => addToAnki(true));
$("cancel-btn").addEventListener("click", () => { $("duplicate-box").hidden = true; });
$("retry-sync-btn").addEventListener("click", async () => {
  try { showSync(await api("/api/sync", {})); }
  catch (err) { showSync({ state: "error", detail: err.message }); }
});

initSettings();
loadInfo();
loadDecks();
refreshSync();
