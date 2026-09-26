"""FastAPI app and routes.

Start with `./run.sh`, which calls `create_app()` through uvicorn's --factory flag.
Routes are plain `def` functions: FastAPI runs them in a thread pool, so the
blocking SDK calls don't stall the server.

The server only talks to the LLM. Anki is reached by the browser, which calls
AnkiConnect on the user's own computer (see app/anki.py and static/app.js).
"""

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.anki import build_note, duplicate_query, note_type
from app.config import ConfigError, Settings, load_settings
from app.masking import check_meaning
from app.notes import build_fields
from app.providers.base import LLMError, LLMProvider
from app.providers.factory import create_provider
from app.schemas import GenerateRequest, GenerateResponse, NoteRequest

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    """Build the app. Tests pass a fake `provider`."""
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            # Stop with a readable message instead of a traceback.
            print(f"Configuration error: {exc}", file=sys.stderr)
            sys.exit(1)

    provider = provider or create_provider(settings)

    app = FastAPI(title="Kanki")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(LLMError)
    def llm_error(_: Request, exc: LLMError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # --- Routes ---

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/info")
    def info():
        """Provider and main model for the UI label, and where the browser finds AnkiConnect."""
        return {
            "provider": provider.display_name,
            "model": provider.model,
            "ankiconnect_url": settings.ankiconnect_url,
        }

    @app.post("/api/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest):
        word = req.word.strip()
        generation = provider.generate(word, req.language, req.num_examples)
        result = generation.result
        return GenerateResponse(
            word=word,  # keep the word exactly as typed
            model=generation.model,
            detected_language=result.detected_language,
            language_code=result.language_code,
            meanings=[check_meaning(m, word) for m in result.meanings],
        )

    @app.get("/api/note-type")
    def get_note_type():
        """createModel parameters, used by the browser if "AI Vocab" does not exist yet."""
        return note_type()

    @app.post("/api/note")
    def make_note(req: NoteRequest):
        """Build the note (HTML-escaped fields) and the duplicate search for the browser."""
        word = req.word.strip()
        fields = build_fields(word, req.language, req.meanings)
        return {
            "note": build_note(req.deck, fields),
            "duplicate_query": duplicate_query(req.deck, word),
        }

    return app
