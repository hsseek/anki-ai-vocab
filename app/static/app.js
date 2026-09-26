// Kanki frontend: plain JavaScript, no build step.
// Model text is always inserted with textContent / value, never innerHTML.
//
// The server generates the content; this page talks to AnkiConnect on the
// computer the browser runs on, so cards go to *this* computer's Anki.

"use strict";

// Languages always offered in the override dropdown. A detected language that
// is not in this list is added to the dropdown automatically.
const LANGUAGES = ["English", "Korean", "Japanese"];

const STORAGE_DECK = "kanki.lastDeck";
const STORAGE_EXAMPLES = "kanki.numExamples";

const $ = (id) => document.getElementById(id);

// Current word and the user's edits for each meaning (same order as the results).
const state = {
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
  for (const id of ["generate-btn", "add-btn", "add-anyway-btn", "language-select"]) {
    $(id).disabled = busy;
  }
}

// ---------------------------------------------------------------------------
// AnkiConnect, called directly from the browser
// ---------------------------------------------------------------------------

const ANKI_UNAVAILABLE = "Open Anki desktop and make sure the AnkiConnect add-on is installed.";
let ankiAllowed = false; // AnkiConnect granted this page access
let modelReady = false;  // the "AI Vocab" note type exists

// Call one AnkiConnect action (API version 6) and return its result.
async function anki(action, params = {}) {
  let response;
  try {
    // No Content-Type header: this keeps it a "simple" request without a CORS preflight.
    response = await fetch(info.ankiconnect_url, {
      method: "POST",
      body: JSON.stringify({ action, version: 6, params }),
    });
  } catch {
    // Anki is closed, AnkiConnect is missing, or it rejected this page's origin.
    throw new Error(ANKI_UNAVAILABLE);
  }
  const data = await response.json().catch(() => null);
  if (!data || !("error" in data) || !("result" in data)) {
    throw new Error("Unexpected response from AnkiConnect. Is the add-on up to date?");
  }
  if (data.error) throw new Error(`AnkiConnect error (${action}): ${data.error}`);
  return data.result;
}

// Ask AnkiConnect for access. The first time, Anki shows a dialog asking
// whether this page may use it; "Yes" adds the page to AnkiConnect's allowlist.
async function connectAnki() {
  if (ankiAllowed) return;
  const res = await anki("requestPermission");
  if (res.permission !== "granted") {
    throw new Error(
      `Anki refused access for ${location.origin}. Reload and click Yes in Anki's dialog, ` +
      `or add ${location.origin} to "webCorsOriginList" in Tools → Add-ons → AnkiConnect → Config, then restart Anki.`
    );
  }
  if (res.requireApikey) {
    throw new Error("AnkiConnect has an API key set (apiKey), which this app does not support. Remove it in the AnkiConnect config.");
  }
  ankiAllowed = true;
}

// Create the "AI Vocab" note type in this computer's Anki if it is missing.
async function ensureModel() {
  if (modelReady) return;
  const noteType = await api("/api/note-type");
  const names = await anki("modelNames");
  if (!names.includes(noteType.modelName)) await anki("createModel", noteType);
  modelReady = true;
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

// From /api/info: provider name, main model and the AnkiConnect address.
const info = { provider: "", model: "", ankiconnect_url: "http://127.0.0.1:8765" };

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
    showStatus("Connecting to Anki… If Anki asks whether this site may access it, click Yes.", "info");
    await connectAnki();
    const decks = await anki("deckNames");
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
  const select = $("num-examples");
  const stored = load(STORAGE_EXAMPLES);
  select.value = ["1", "2", "3"].includes(stored) ? stored : "2";
  select.addEventListener("change", () => save(STORAGE_EXAMPLES, select.value));
}

// ---------------------------------------------------------------------------
// Step 1: generate
// ---------------------------------------------------------------------------

async function generate(word, language = null) {
  setBusy(true);
  $("duplicate-box").hidden = true;
  showStatus(language ? `Regenerating as ${language}…` : "Generating…", "info");
  try {
    const result = await api("/api/generate", {
      word,
      language,
      num_examples: Number($("num-examples").value),
    });
    state.result = result;
    showModel(result.model);
    state.edits = result.meanings.map((m) => ({
      part_of_speech: m.part_of_speech,
      definition: m.definition,
      examples: [...m.examples],
      examples_masked: [...m.examples_masked],
      synonyms: m.synonyms.join(", "),
    }));
    state.selected = new Set();
    hideStatus();
    renderResults();
  } catch (err) {
    showStatus(err.message, "error");
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------------------
// Step 2: language and meaning selection
// ---------------------------------------------------------------------------

function renderResults() {
  const { result } = state;

  // Language dropdown: the fixed list plus the detected language if missing.
  const languages = [...LANGUAGES];
  if (!languages.includes(result.detected_language)) languages.push(result.detected_language);
  const langSelect = $("language-select");
  langSelect.replaceChildren(...languages.map((l) => el("option", { value: l, textContent: l })));
  langSelect.value = result.detected_language;

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

// The note as edited in the preview, in the shape /api/note expects.
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
  // Anki may have been opened after this page loaded: fetch the decks again.
  if (!$("deck-select").value && !(await loadDecks())) return;

  const request = buildNoteRequest();
  if (!request.word) return showStatus("The Word field is empty.", "error");
  if (!request.deck) return showStatus("Choose a deck first.", "error");
  if (request.meanings.length === 0) return showStatus("Select at least one meaning.", "error");

  setBusy(true);
  $("duplicate-box").hidden = true;
  try {
    await connectAnki();
    // The server builds the HTML-escaped fields and the duplicate search.
    const { note, duplicate_query } = await api("/api/note", request);

    if (!allowDuplicate) {
      const existing = await anki("findNotes", { query: duplicate_query });
      if (existing.length > 0) {
        $("duplicate-box").hidden = false;
        hideStatus();
        return;
      }
    }

    await ensureModel();
    await anki("addNote", {
      // duplicateScope "deck" matches our own check: duplicates only count within a deck.
      note: { ...note, options: { allowDuplicate, duplicateScope: "deck" } },
    });
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
  if (word) generate(word);
});

$("language-select").addEventListener("change", () => {
  if (state.result) generate(state.result.word, $("language-select").value);
});

$("deck-select").addEventListener("change", () => save(STORAGE_DECK, $("deck-select").value));
$("add-btn").addEventListener("click", () => addToAnki(false));
$("add-anyway-btn").addEventListener("click", () => addToAnki(true));
$("cancel-btn").addEventListener("click", () => { $("duplicate-box").hidden = true; });

initSettings();
// The AnkiConnect address comes from /api/info, so load decks after it.
loadInfo().then(loadDecks);
