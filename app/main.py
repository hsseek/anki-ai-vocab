"""FastAPI app and routes.

Start with `./run.sh`, which calls `create_app()` through uvicorn's --factory flag.
Routes are plain `def` functions: FastAPI runs them in a thread pool, so the
blocking SDK calls don't stall the server.

The server only talks to the LLM. Anki is reached by the browser, which calls
AnkiConnect on the user's own computer (see app/anki.py and static/app.js).
"""

import sys
import json
import logging
import secrets
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.anki import build_note, duplicate_query, note_type
from app.config import ConfigError, Settings, load_settings
from app.masking import check_meaning
from app.metrics import emit_metric
from app.notes import build_fields
from app.providers.base import LLMError, LLMProvider
from app.providers.factory import create_provider
from app.schemas import ClientGenerationMetric, GenerateRequest, GenerateResponse, NoteRequest

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

    @app.post("/api/generate/stream")
    def generate_stream(req: GenerateRequest):
        word = req.word.strip()
        request_id = secrets.token_hex(6)

        def events():
            def encode(event):
                return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

            try:
                with closing(provider.stream(
                    word, req.language, req.num_examples, request_id=request_id
                )) as stream:
                    for event in stream:
                        if event["type"] == "meaning":
                            event = {
                                **event,
                                "meaning": check_meaning(event["meaning"], word).model_dump(),
                            }
                        elif event["type"] == "done":
                            result = event["result"]
                            event = {"type": "done", "result": GenerateResponse(
                                word=word, model=event["model"],
                                detected_language=result.detected_language,
                                language_code=result.language_code,
                                meanings=[check_meaning(m, word) for m in result.meanings],
                            ).model_dump()}
                        yield encode(event)
            except LLMError as exc:
                emit_metric(
                    "generation_failed", request_id, provider=provider.display_name,
                    error_type=type(exc).__name__,
                )
                yield encode({"type": "error", "detail": str(exc)})
            except Exception as exc:
                emit_metric(
                    "generation_failed", request_id, provider=provider.display_name,
                    error_type=type(exc).__name__,
                )
                logging.getLogger(__name__).exception("Vocabulary stream failed")
                yield encode({"type": "error", "detail": "Generation failed. Please try again."})

        return StreamingResponse(events(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        })

    @app.post("/api/metrics/client", status_code=204)
    def client_metric(metric: ClientGenerationMetric):
        emit_metric(
            "client_" + metric.event, metric.request_id,
            elapsed_ms=metric.elapsed_ms,
        )
        return Response(status_code=204)

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
