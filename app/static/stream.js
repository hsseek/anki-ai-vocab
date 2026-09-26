// Read our SSE endpoint over POST. Each event has one JSON data line.
// A streaming decoder preserves Unicode characters split across network chunks.
"use strict";

async function readGenerationStream(response, onEvent) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).join("; ") : data.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = false;

  function consume() {
    let end;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (!frame.startsWith("data: ")) continue;
      const event = JSON.parse(frame.slice(6));
      if (event.type === "error") throw new Error(event.detail);
      onEvent(event);
      if (event.type === "done") complete = true;
    }
  }

  try {
    while (!complete) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      consume();
      if (done) break;
    }
    if (!complete) throw new Error("Connection ended before generation finished. Please try again.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
