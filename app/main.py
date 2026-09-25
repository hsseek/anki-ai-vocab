"""FastAPI app and routes.

Start with `./run.sh`, which calls `create_app()` through uvicorn's --factory flag.
Routes are plain `def` functions: FastAPI runs them in a thread pool, so the
blocking SDK and HTTP calls don't stall the server.
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.anki import AnkiClient, AnkiError, AnkiUnavailableError
from app.config import ConfigError, Settings, load_settings
from app.masking import check_meaning
from app.notes import build_fields
from app.providers.base import LLMError, LLMProvider
from app.providers.factory import create_provider
from app.schemas import AddNoteRequest, GenerateRequest, GenerateResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"
log = logging.getLogger("kanki")


def create_app(
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    anki: AnkiClient | None = None,
) -> FastAPI:
    """Build the app. Tests pass fake `provider` and `anki` objects."""
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            # Stop with a readable message instead of a traceback.
            print(f"Configuration error: {exc}", file=sys.stderr)
            sys.exit(1)

    provider = provider or create_provider(settings)
    anki = anki or AnkiClient(settings.ankiconnect_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Create the note type now if Anki is already open.
        try:
            anki.ensure_model()
        except AnkiError as exc:
            # Not fatal: add_note tries again on the first add.
            log.warning("Could not prepare the note type yet: %s", exc)
        yield

    app = FastAPI(title="Kanki", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- Error handlers: return {"detail": message} with a matching status ---

    @app.exception_handler(AnkiUnavailableError)
    def anki_unavailable(_: Request, exc: AnkiUnavailableError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(AnkiError)
    def anki_error(_: Request, exc: AnkiError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(LLMError)
    def llm_error(_: Request, exc: LLMError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # --- Routes ---

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/info")
    def info():
        """The active provider and main model, shown as a label in the UI."""
        return {"provider": provider.display_name, "model": provider.model}

    @app.get("/api/decks")
    def decks():
        return {"decks": anki.deck_names()}

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

    @app.post("/api/add")
    def add(req: AddNoteRequest):
        """Add a note. Returns status "duplicate" instead of adding if one exists."""
        word = req.word.strip()
        if not req.allow_duplicate:
            existing = anki.find_duplicates(req.deck, word)
            if existing:
                return {"status": "duplicate", "note_ids": existing}

        fields = build_fields(word, req.language, req.meanings)
        note_id = anki.add_note(req.deck, fields, allow_duplicate=req.allow_duplicate)
        return {"status": "added", "note_id": note_id}

    return app
