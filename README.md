# Kanki

A small local web app that turns a word into an Anki vocabulary note.
You type a word, an LLM (Claude, OpenAI or Gemini) writes its meanings, definitions,
examples and synonyms in the word's own language, you pick meanings and edit
the preview, and the app adds one note to desktop Anki through AnkiConnect.

- Works with any language the model knows; definitions and examples stay in
  the word's language, never translated.
- Creates a note with a forward card (word → meaning) and a reverse card
  (definition + examples with the word blanked out → word).
- Runs only on your machine (`127.0.0.1`). API keys stay on the server and
  never reach the browser.

Requires Python 3.10+ and Anki desktop.

## Setup (Ubuntu)

1. **Install Anki and AnkiConnect.**
   Install Anki desktop from <https://apps.ankiweb.net>. In Anki, open
   *Tools → Add-ons → Get Add-ons…*, enter the code `2055492159`, then restart Anki.
   Keep Anki open while you use Kanki.

2. **Get the code, create a virtual environment and install the requirements.**

   ```bash
   git clone <this repo's URL> && cd <repo folder>
   sudo apt install python3-venv   # if not installed yet
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

3. **Configure the app.**

   ```bash
   cp .env.example .env
   vim .env
   ```

   Set `LLM_PROVIDER` to `claude`, `openai` or `gemini`, then fill in the
   matching API key and model name:

   | `LLM_PROVIDER` | Required settings                        | Cost |
   |----------------|------------------------------------------|------|
   | `claude`       | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`   | paid |
   | `openai`       | `OPENAI_API_KEY`, `OPENAI_MODEL`         | paid |
   | `gemini`       | `GEMINI_API_KEY`, `GEMINI_MODEL`         | free tier available |

   **Free option (Gemini):** sign in at <https://aistudio.google.com/apikey> with a
   Google account and create an API key (no credit card needed). Pick a model name
   from the model list in AI Studio; "Flash" models have the most generous free
   limits. The free tier has daily request limits, and Google may use free-tier
   requests to improve its products.

   **Fallback models:** a model setting can list several models separated by
   commas, for example `GEMINI_MODEL=gemini-flash-latest,gemini-flash-lite-latest`.
   The first is used normally. When it is overloaded, rate-limited or times
   out, the app tries the next one, and the label at the top shows
   "(fallback)". Other errors, such as a wrong API key, are shown right away.

   `ANKICONNECT_URL` defaults to `http://127.0.0.1:8765`.

   `.env` holds your API key and is listed in `.gitignore`, so it is never committed.

4. **Run it.**

   ```bash
   ./run.sh
   ```

   Open <http://127.0.0.1:8000>. The server listens on `127.0.0.1` only.
   Set `PORT=8001 ./run.sh` to use another port.

5. **Switch providers** by changing `LLM_PROVIDER` in `.env` and restarting the server.

## Using it

1. Type a word or short phrase and press Enter.
2. Check the detected language. Pick another language from the dropdown to regenerate.
3. Tick one or more meanings. Edit anything in the preview.
   - ⚠ *contains the word* next to a definition means the definition gives the answer away.
   - ⚠ *auto-masked, please check* means the model left the word in a masked
     sentence and the app masked it with a simple pattern. Check that it looks right.
4. Choose a deck (your last choice is remembered) and click **Add to Anki**.
   If the word already exists in that deck, you can **Add anyway** or **Cancel**.

The number of example sentences per meaning (1–3) is in the top right.

## The "AI Vocab" note type

Created automatically on first use. Fields: `Word`, `Language`, `Definition`,
`Examples`, `ExamplesMasked`, `Synonyms`. Notes are tagged `ai-vocab`.

- **Forward** card: word → definition, examples, synonyms.
- **Reverse** card: definition and masked examples → word.

When several meanings are selected they share one note, numbered the same way in every field.

## Tests

```bash
.venv/bin/python -m pytest
```

The tests mock the LLM SDKs and AnkiConnect and make no network calls.

## Project layout

```
app/main.py              FastAPI app and routes
app/config.py            .env loading and validation
app/schemas.py           Pydantic models shared by providers and routes
app/prompts.py           the shared system prompt
app/providers/           LLMProvider interface, Claude/OpenAI/Gemini providers, factory
app/anki.py              AnkiConnect client and the note type
app/notes.py             builds the note's HTML fields
app/masking.py           fallback masking and checks
app/static/              HTML, CSS, JavaScript
tests/                   pytest tests
```
