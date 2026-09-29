const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "../app/static");
const encoder = new TextEncoder();
const tick = () => new Promise((resolve) => setImmediate(resolve));
const frame = (event) => encoder.encode("data: " + JSON.stringify(event) + "\n\n");

function environment() {
  class Element {
    constructor(tag = "div") {
      this.tagName = tag;
      this.children = [];
      this.listeners = {};
      this.value = "";
      this.hidden = true;
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    get options() { return this.children; }
    focus() {}
  }
  const nodes = new Map();
  const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
  for (const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)) {
    nodes.set(match[2], new Element(match[1]));
  }
  function fields(root) {
    return root.children.flatMap((child) => typeof child === "string" ? [] : [
      ...(["input", "textarea", "select"].includes(child.tagName) ? [child] : []),
      ...fields(child),
    ]);
  }
  // Our minimal DOM connects roots used by querySelectorAll.
  nodes.get("results").append(nodes.get("meanings"));
  nodes.get("preview").append(nodes.get("meaning-editors"), nodes.get("field-word"),
    nodes.get("field-language"), nodes.get("deck-select"));
  const storage = new Map([["kanki.language", "English"]]);
  const context = vm.createContext({
    console, TextDecoder, document: {
      getElementById: (id) => nodes.get(id),
      createElement: (tag) => new Element(tag),
      querySelectorAll: () => [...fields(nodes.get("results")), ...fields(nodes.get("preview"))],
    },
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    fetch: () => new Promise(() => {}), // startup calls remain pending; no network
  });
  vm.runInContext(fs.readFileSync(path.join(staticDir, "stream.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(staticDir, "app.js"), "utf8"), context);
  return { context, nodes, storage, fields };
}

const meaning = {
  part_of_speech: "verb", label: "move", definition: "Move quickly.",
  examples: ["She ran home."], examples_masked: ["She ___ home."],
  synonyms: ["sprint"], masked_flags: [false], definition_warning: false,
};
const result = { word: "run", detected_language: "English", language_code: "en",
  model: "test", meanings: [meaning] };

test("SSE decoder handles split Unicode, multiple frames, and closes after done", async () => {
  const { context } = environment();
  const text = "data: " + JSON.stringify({ type: "meaning", label: "달리다" }) +
    "\n\ndata: " + JSON.stringify({ type: "done" }) + "\n\n";
  let cancelled = false;
  const events = [];
  const bytes = encoder.encode(text);
  const body = new ReadableStream({
    start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); },
    cancel() { cancelled = true; },
  });
  await context.readGenerationStream(new Response(body), (event) => events.push(event));
  assert.equal(events[0].label, "달리다");
  assert.equal(events[1].type, "done");
  assert.equal(cancelled, true);
});

test("SSE decoder rejects errors and truncated streams", async () => {
  const { context } = environment();
  await assert.rejects(context.readGenerationStream(
    new Response(frame({ type: "start" })), () => {}), /before generation finished/);
  await assert.rejects(context.readGenerationStream(
    new Response(frame({ type: "error", detail: "Rate limit" })), () => {}), /Rate limit/);
  await assert.rejects(context.readGenerationStream(
    new Response(JSON.stringify({ detail: "Invalid word" }), { status: 422 }), () => {}), /Invalid word/);
});

test("First meaning is visible before completion; defaults, editing and reset work", async () => {
  const { context, nodes, storage, fields } = environment();
  let controller;
  let request;
  context.fetch = async (url, options) => {
    request = JSON.parse(options.body);
    return new Response(new ReadableStream({ start(c) { controller = c; } }));
  };
  nodes.get("word-input").value = "run";
  assert.equal(nodes.get("language-select").value, "English");
  const pending = context.generate("run", "English");
  await tick();
  assert.equal(request.language, "English");
  controller.enqueue(frame({ type: "start", model: "test", attempt: 1 }));
  controller.enqueue(frame({ type: "meaning", meaning, detected_language: "English", language_code: "en" }));
  await tick();
  assert.equal(nodes.get("preview").hidden, false);
  assert.equal(nodes.get("add-btn").disabled, true);
  const boxes = fields(nodes.get("results"));
  assert.equal(boxes.length, 1);
  assert.equal(boxes[0].checked, true);
  assert.equal(boxes[0].disabled, true);
  assert.equal(vm.runInContext("state.selected.size", context), 1);
  controller.enqueue(frame({ type: "done", result }));
  await pending;
  assert.equal(nodes.get("add-btn").disabled, false);
  assert.equal(fields(nodes.get("results"))[0].disabled, false);
  const checkbox = fields(nodes.get("results"))[0];
  checkbox.checked = false;
  checkbox.listeners.change();
  assert.equal(nodes.get("preview").hidden, true);
  checkbox.checked = true;
  checkbox.listeners.change();
  assert.equal(nodes.get("preview").hidden, false);
  context.resetForNextWord();
  assert.equal(nodes.get("word-input").value, "");
  assert.equal(nodes.get("language-select").value, "English");
  assert.equal(storage.get("kanki.language"), "English");
});

test("Retry clears provisional results and failure cannot leave an addable note", async () => {
  const { context, nodes } = environment();
  let controller;
  context.fetch = async () => new Response(new ReadableStream({ start(c) { controller = c; } }));
  const pending = context.generate("run");
  await tick();
  controller.enqueue(frame({ type: "start", model: "a", attempt: 1 }));
  controller.enqueue(frame({ type: "meaning", meaning }));
  await tick();
  assert.equal(nodes.get("preview").hidden, false);
  controller.enqueue(frame({ type: "start", model: "b", attempt: 1 }));
  await tick();
  assert.equal(nodes.get("preview").hidden, true);
  assert.equal(vm.runInContext("state.selected.size", context), 0);
  controller.enqueue(frame({ type: "meaning", meaning }));
  controller.close(); // no done event
  await pending;
  assert.equal(nodes.get("preview").hidden, true);
  assert.equal(vm.runInContext("state.result", context), null);
  assert.match(nodes.get("status").textContent, /before generation finished/);
  let called = false;
  context.fetch = () => { called = true; };
  await context.addToAnki();
  assert.equal(called, false);
});

test("Add goes to server and displays separate sync status", async () => {
  const { context, nodes } = environment();
  context.result = result;
  vm.runInContext("state.result = result; state.edits = [{...result.meanings[0], synonyms: 'sprint'}]; state.selected = new Set([0]);", context);
  nodes.get("field-word").value = "run";
  nodes.get("field-language").value = "English";
  nodes.get("deck-select").value = "Vocab";
  const requests = [];
  context.fetch = async (url, options) => {
    requests.push([url, JSON.parse(options.body)]);
    return new Response(JSON.stringify({ duplicate: false, note_id: 12,
      sync: { state: "finished", detail: "" } }), {
      headers: { "Content-Type": "application/json" },
    });
  };
  await context.addToAnki();
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/api/add?allow_duplicate=false");
  assert.equal(requests[0][1].word, "run");
  assert.match(nodes.get("sync-status").textContent, /sync finished/);
  assert.equal(nodes.get("word-input").value, "");
});
