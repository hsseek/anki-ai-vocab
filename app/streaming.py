"""Read only complete meaning objects from a JSON document arriving in chunks.

JSONDecoder handles quotes, escapes, nested arrays and braces inside strings.
Partial objects are never shown. The complete document is validated separately.
"""

import json


class MeaningParser:
    def __init__(self):
        self.text = ""
        self.position = 0
        self.mode = "object"
        self.started = False
        self.metadata = {}
        self.decoder = json.JSONDecoder()

    def feed(self, chunk: str) -> list[dict]:
        self.text += chunk
        complete = []
        while True:
            pos = self.position
            while pos < len(self.text) and self.text[pos] in " \r\n\t,":
                pos += 1
            if pos >= len(self.text):
                return complete
            if not self.started:
                if self.text[pos] != "{":
                    raise ValueError("Expected a JSON object")
                self.started = True
                self.position = pos + 1
                continue
            if self.mode == "meanings":
                if self.text[pos] == "]":
                    self.mode = "object"
                    self.position = pos + 1
                    continue
                try:
                    meaning, end = self.decoder.raw_decode(self.text, pos)
                except json.JSONDecodeError:
                    return complete
                if not isinstance(meaning, dict):
                    raise ValueError("Expected a meaning object")
                complete.append(meaning)
                self.position = end
                continue
            if self.text[pos] == "}":
                return complete
            try:
                key, end = self.decoder.raw_decode(self.text, pos)
                while end < len(self.text) and self.text[end].isspace():
                    end += 1
                if end >= len(self.text):
                    return complete
                if self.text[end] != ":":
                    raise ValueError("Expected a JSON field")
                end += 1
                while end < len(self.text) and self.text[end].isspace():
                    end += 1
                if end >= len(self.text):
                    return complete
                if key == "meanings":
                    if self.text[end] != "[":
                        raise ValueError("Expected a meanings array")
                    self.mode = "meanings"
                    self.position = end + 1
                    continue
                value, end = self.decoder.raw_decode(self.text, end)
            except json.JSONDecodeError:
                return complete
            self.metadata[key] = value
            self.position = end
