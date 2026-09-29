"""FastAPI app and routes.

Start with `./run.sh`, which calls `create_app()` through uvicorn's --factory flag.
Routes are plain `def` functions: FastAPI runs them in a thread pool, so the
blocking SDK calls don't stall the server.

AnkiConnect is reached on the server, using the login ID passed by Caddy.
"""

import sys
import json
import logging
import secrets
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.anki import note_type
from app.config import ConfigError, Settings, load_settings
from app.masking import check_meaning
from app.metrics import emit_metric
from app.server_anki import AnkiError, ServerAnki
from app.providers.base import LLMError, LLMProvider
from app.providers.factory import create_provider
from app.schemas import ClientGenerationMetric, GenerateRequest, GenerateResponse, NoteRequest

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None,
               anki: ServerAnki | None = None) -> FastAPI:
    """Build the app. Tests pass a fake `provider`."""
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            # Stop with a readable message instead of a traceback.
            print(f"Configuration error: {exc}", file=sys.stderr)
            sys.exit(1)

    provider = provider or create_provider(settings)
    anki = anki or ServerAnki(settings.anki_users, Path.home() / ".local/state/kanki")

    app = FastAPI(title="Kanki")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(LLMError)
    def llm_error(_: Request, exc: LLMError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(AnkiError)
    def anki_error(_: Request, exc: AnkiError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    def login_user(request: Request) -> str:
        user = request.headers.get("x-kanki-user", "")
        if user not in anki.ports:
            raise HTTPException(status_code=401, detail="Unknown or missing login.")
        return user

    # --- Routes ---

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/info")
    def info():
        """Provider and main model for the UI label."""
        return {
            "provider": provider.display_name,
            "model": provider.model,
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

    @app.get("/api/decks")
    def decks(request: Request):
        return anki.decks(login_user(request))

    @app.post("/api/add")
    def add_note(req: NoteRequest, request: Request, allow_duplicate: bool = False):
        return anki.add(login_user(request), req, allow_duplicate)

    @app.get("/api/sync")
    def sync_status(request: Request):
        return anki.status(login_user(request))

    @app.post("/api/sync")
    def retry_sync(request: Request):
        return anki.retry_sync(login_user(request))

    return app
