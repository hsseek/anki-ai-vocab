# Kanki

A small local web app that turns a word into an Anki vocabulary note.
You type a word, an LLM (Claude, OpenAI or Gemini) writes its meanings, definitions,
examples and synonyms in the word's own language, you pick meanings and edit
the preview, and the server adds one note to your own Anki profile. It then
starts an AnkiWeb sync in the background.

- Works with any language the model knows; definitions and examples stay in
  the word's language, never translated.
- Creates a note with a forward card (word → meaning) and a reverse card
  (definition + examples with the word blanked out → word).
- Open it from any browser. Only the server needs Anki and AnkiConnect.
- API keys stay on the server and never reach the browser.

Requires Python 3.10+ and Anki desktop.

## Setup (Ubuntu)

1. **Install Anki on the server.** Install Anki desktop from
   <https://apps.ankiweb.net>. AnkiConnect is installed once in each isolated
   server Anki instance below.

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

   Set `ANKI_USERS` to the Caddy login IDs and their separate loopback
   AnkiConnect ports, for example `sun:8765,kay:8766`.

   `.env` holds your API key and is listed in `.gitignore`, so it is never committed.

4. **Run it after configuring the Anki profiles below.**

   ```bash
   ./run.sh
   ```

   Open <http://127.0.0.1:8000>. The server listens on `127.0.0.1` only.
   Set `PORT=8001 ./run.sh` to use another port.

   For use without Caddy, requests to Anki routes need an authenticated
   `X-Kanki-User` header. The Caddy configuration supplies this after login.

5. **Switch providers** by changing `LLM_PROVIDER` in `.env` and restarting the server.

## Running on a server (open it from any computer)

The server runs one isolated Anki instance per login. Each uses a separate
data folder, AnkiWeb account, AnkiConnect port and virtual display. Caddy
passes the verified login ID to the app; the app never accepts a profile or
AnkiConnect URL from the browser.

On the server, [Caddy](https://caddyserver.com) sits in front of the app. It
gets a free HTTPS certificate and asks for an ID and password on every
request. The app itself only listens on `127.0.0.1`.

```
browser ──HTTPS + ID/password──▶ Caddy (443) ──▶ app (127.0.0.1:8000) ──▶ LLM
                                              └──▶ user's AnkiConnect ──▶ AnkiWeb
```

You need a domain name pointing to your home IP (a router's DDNS name works,
e.g. `name.iptime.org`), and your router must forward **TCP 443 and 80** to the
server. Port 80 is used to issue and renew the certificate and to redirect to
HTTPS.

1. **App.** Clone the repo to `~/anki-ai-vocab`, then create the virtual
   environment and `.env` as in Setup. Run it as a user service on `127.0.0.1`:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp deploy/anki-ai-vocab.service ~/.config/systemd/user/
   loginctl enable-linger $USER      # keep it running after logout
   systemctl --user daemon-reload
   systemctl --user enable --now anki-ai-vocab
   ```

2. **HTTPS and logins.** Run once, with your domain and the login IDs. It
   installs Caddy from its official repository, asks for an optional email
   (for certificate notices, and for the ZeroSSL fallback when Let's Encrypt
   refuses, which can happen with shared DDNS domains), then asks for each
   password. Only bcrypt hashes are stored, in `/etc/caddy/anki-ai-vocab.users`.

   ```bash
   sudo deploy/setup-caddy.sh name.iptime.org sun kay
   ```

   Later: `sudo deploy/set-password.sh ID` adds a login or changes a password,
   and `sudo deploy/set-password.sh --delete ID` removes one.

   **If public certificates are refused** for your domain (for example
   `*.iptime.org`, whose DNS forbids all certificate authorities), add
   `--private-cert`. Caddy then issues its own certificate, and each computer
   must install its root certificate once (see below):

   ```bash
   sudo deploy/setup-caddy.sh --private-cert name.iptime.org sun kay
   ```

3. **Configure one server Anki per login.** Install `xvfb`, `xauth`, and a
   temporary VNC viewer server for the first setup, along with Anki's Linux
   dependencies. On Ubuntu, `sudo deploy/install-server-prereqs.sh` installs
   these dependencies and enables the authenticated Caddy login header. Then:

   ```bash
   deploy/configure-anki-profile.sh sun 8765 91
   deploy/configure-anki-profile.sh kay 8766 92
   ```

   If Anki is unpacked in your home directory instead of installed on the
   system path, prefix each configure command with
   `KANKI_ANKI_BIN=/absolute/path/to/anki`.

   `configure-anki-profile.sh` creates a separate data folder and a user
   service for each login. Do not reuse an existing Anki data folder. The
   service installs the bundled sync-status hook. Install AnkiConnect in each
   profile (add-on code `2055492159`) and set its `webBindAddress` to
   `127.0.0.1` and `webBindPort` to that profile's configured port. The
   deployment can also preinstall the official `.ankiaddon` package with
   `deploy/install-ankiconnect.py` before starting a new profile.

   To view a profile's virtual display for first-time setup, attach `x11vnc`
   over an SSH tunnel. For `sun`, run on your laptop:

   ```bash
   ssh -L 5991:127.0.0.1:5991 g3 \
     'x11vnc -display :91 -auth ~/.config/kanki/xauth-sun -localhost -nopw -rfbport 5991'
   ```

   Connect a VNC viewer to `127.0.0.1:5991`. In that Anki window, sign in to
   **sun's own** AnkiWeb account. If the account already has cards, choose **Download**
   during the first sync; if it is empty, choose **Upload**. Repeat for `kay`
   with display `:92`, port `5992` for the tunnel, AnkiConnect port `8766`,
   and kay's separate AnkiWeb account. Restart each service after installing
   AnkiConnect or changing its port:

   ```bash
   systemctl --user restart anki-profile@sun anki-profile@kay
   ```

   The first sync direction matters: choosing Upload over an existing
   AnkiWeb collection can replace its contents. Make a backup before setup.
   Once both profiles respond on their configured ports, restart the web app.

4. **Each computer.** Open `https://<your domain>` and log in. The page lists
   decks from that login's server Anki. After a card is added, the separate
   sync line shows queued, running or finished. On failure it offers Retry.
   No client-side Anki or AnkiConnect installation is needed.

   When upgrading an existing Caddy installation, run
   `sudo deploy/enable-caddy-user-header.sh` once so Caddy forwards the
   authenticated login ID to the app.

### Installing the private root certificate (only with `--private-cert`)

Download `https://<your domain>/root.crt` (the browser warns until the root is
installed; `curl -k` works too) and check that its SHA-256 fingerprint matches
the one `setup-caddy.sh` printed:

```bash
openssl x509 -in root.crt -noout -fingerprint -sha256
```

Then install it:

- **Linux, Chrome/Chromium:** they use their own certificate store.
  `sudo apt install libnss3-tools`, then
  `certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n "anki-ai-vocab" -i root.crt`
- **Linux, Firefox:** Settings → Privacy & Security → Certificates → View
  Certificates → Authorities → Import, and tick "Trust this CA to identify websites".
- **Windows (Chrome, Edge):** double-click `root.crt` → Install Certificate →
  Current User → "Trusted Root Certification Authorities".
- **macOS:** open it in Keychain Access (login keychain), then set it to "Always Trust".

Restart the browser afterwards. Install the root only on computers you trust
the server with: a trusted root can vouch for *any* website, so whoever controls
the server could impersonate other sites to those computers.

Everyone who logs in uses the server's API key and quota, so use long, unique
passwords. After changing the code: `git pull` on the server, then
`systemctl --user restart anki-ai-vocab`. Logs: `journalctl --user -u anki-ai-vocab`
(app) and `journalctl -u caddy` (HTTPS and logins).

### Generation performance logs

Each generation writes privacy-safe JSON timing records to the app's systemd
journal. They include the provider and model, retries/fallbacks, time to the
first provider chunk, first complete meaning, total generation time, and
browser-observed delivery time. Words, definitions, examples, API keys and
passwords are never logged.

View raw metrics or summarize all retained runs:

```bash
journalctl --user -u anki-ai-vocab -o cat | grep '"metric"'
journalctl --user -u anki-ai-vocab -o cat | \
  ~/anki-ai-vocab/.venv/bin/python ~/anki-ai-vocab/scripts/summarize_metrics.py
```

The summary reports the median (p50) and 95th-percentile (p95) latency per
model for the provider, server and browser milestones, plus invalid responses
and model-unavailable fallbacks. The gap between server and browser timings
shows delivery overhead. Collect several normal words per language before
comparing models.

## Using it

1. Choose a language (or leave Auto-detect), type a word or short phrase and press Enter.
2. Check the detected language. Pick another language from the dropdown to regenerate.
3. Meanings appear as they arrive, with all meanings selected by default.
   Once generation finishes, uncheck any you do not want and edit the preview.
   - ⚠ *contains the word* next to a definition means the definition gives the answer away.
   - ⚠ *auto-masked, please check* means the model left the word in a masked
     sentence and the app masked it with a simple pattern. Check that it looks right.
4. Choose a deck (your last choice is remembered) and click **Add to Anki**.
   If the word already exists in that deck, you can **Add anyway** or **Cancel**.

The number of example sentences per meaning (1–3) is in the top right.
Language selection is available before generation and remembered in this browser.
Detection happens in the same LLM request as content generation; choosing a language
mainly avoids regenerating after incorrect detection. For less waiting, select one
example per meaning. The shared prompt requests concise definitions and examples
while retaining all common meanings. Actual latency depends on the model and API load.

Generation streams completed meanings into the preview. Editing and adding to Anki
become available after the full response passes validation. A retry or fallback
clears provisional results; a failed or interrupted stream cannot be added as a note.
The model writes each example once, marking every target form with double brackets
(for example, `She [[ran]] home.`). The server derives both `She ran home.` and
`She ___ home.` from that sentence. No marker syntax reaches Anki, and the existing
Forward and Reverse card types remain unchanged.

New Anki cards abbreviate English part-of-speech labels: noun → n, verb → v,
adjective → adj, adverb → adv, pronoun → pron, preposition → prep,
conjunction → conj, interjection → interj, determiner → det, article → art.
Other language labels are preserved. Existing Anki notes are not modified.

## The "AI Vocab" note type

Created automatically on first use. Fields: `Word`, `Language`, `Definition`,
`Examples`, `ExamplesMasked`, `Synonyms`. Notes are tagged `ai-vocab`.

- **Forward** card: word → definition, examples, synonyms.
- **Reverse** card: definition and masked examples → word.

When several meanings are selected they share one note, numbered the same way in every field.

## Tests

```bash
.venv/bin/python -m pytest
node --test tests/test_frontend.cjs
```

Tests mock all LLM SDKs and the per-user AnkiConnect calls; they make no real
network calls. The frontend tests require Node.js 18+ only for testing.

## Project layout

```
app/main.py              FastAPI app and routes
app/config.py            .env loading and validation
app/schemas.py           Pydantic models shared by providers and routes
app/prompts.py           the shared system prompt
app/providers/           LLMProvider interface, Claude/OpenAI/Gemini providers, factory
app/anki.py              the note type, note and duplicate query for AnkiConnect
app/server_anki.py       per-login AnkiConnect access and sync status
app/notes.py             builds the note's HTML fields
app/masking.py           fallback masking and checks
app/static/              HTML, CSS and JavaScript
deploy/                  server setup, Anki profile services, Caddy and logins
tests/                   pytest tests
```
