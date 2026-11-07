import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi.exceptions import RequestValidationError

from nexus_api.http.platform import router as platform_router
from nexus_api.http.skills import router as skills_router
from nexus_api.http.orgs import router as orgs_router
from nexus_api.http.memberships import router as memberships_router
from nexus_api.http.shared_spaces import router as shared_spaces_router
from nexus_api.http.agent_shares import router as agent_shares_router
from nexus_platform.errors import PlatformError
from nexus_knowledge.capabilities import CapabilityPlanned
from nexus_platform.configuration import DatabaseConfigurationError
from nexus_platform.bootstrap import ensure_default_enterprise
from nexus_platform.persistence.database import create_database_engine, session_factory

logger = logging.getLogger("nexus_api.startup")


def ensure_default_space() -> None:
    """Create the default enterprise space and owner account if missing. Never stops the API from starting."""
    try:
        engine = create_database_engine()
    except DatabaseConfigurationError as exc:
        logger.warning("Default space bootstrap skipped: %s", exc)
        return
    try:
        with session_factory(engine)() as db:
            result = ensure_default_enterprise(db)
        logger.info("Default space bootstrap: space=%s owner=%s created_space=%s created_owner=%s granted_membership=%s",
                    result.space_id, result.owner_id, result.created_space, result.created_owner,
                    result.granted_membership)
    except SQLAlchemyError as exc:
        logger.warning("Default space bootstrap skipped; apply migrations first: %s", exc)
    except Exception:
        logger.exception("Default space bootstrap failed")
    finally:
        engine.dispose()


def install_knowledge_embedder() -> None:
    """Let the retrieval test embed queries with the searcher's own key (openspec 2026-11-06-knowledge-base)."""
    from nexus_platform.knowledge.embedding import set_embedder_factory
    from nexus_worker.knowledge_index import knowledge_embedder
    set_embedder_factory(knowledge_embedder)
    from nexus_platform.knowledge.rerank import set_reranker_factory
    from nexus_worker.knowledge_index import knowledge_reranker
    set_reranker_factory(knowledge_reranker)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_default_space()
    install_knowledge_embedder()
    yield


app = FastAPI(title="Hyoga Nexus", version="0.1.0", lifespan=lifespan)

from nexus_api.security import DevelopmentLoopbackGuard  # noqa: E402
app.add_middleware(DevelopmentLoopbackGuard)
app.include_router(platform_router)
app.include_router(skills_router)
app.include_router(orgs_router)
app.include_router(memberships_router)
app.include_router(shared_spaces_router)
app.include_router(agent_shares_router)
from nexus_api.http.agent_editor import router as agent_editor_router
app.include_router(agent_editor_router)
from nexus_api.http.model_settings import router as model_settings_router
app.include_router(model_settings_router)
from nexus_api.http.native import router as native_router
app.include_router(native_router)
from nexus_api.http.roles import router as roles_router
app.include_router(roles_router)
from nexus_api.http.auth import router as auth_router
app.include_router(auth_router)
from nexus_api.http.knowledge import router as knowledge_router
app.include_router(knowledge_router)
from nexus_api.http.knowledge_wiki import router as knowledge_wiki_router
app.include_router(knowledge_wiki_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, exc: PlatformError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": str(exc), "request_id": request.state.request_id}},
    )


@app.exception_handler(CapabilityPlanned)
async def capability_planned_handler(request: Request, exc: CapabilityPlanned):
    # A write chose a cataloged knowledge feature that is not implemented yet (openspec 2026-11-06-knowledge-base).
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "capability_planned", "message": str(exc),
                            "details": {"group": exc.item.group, "key": exc.item.key, "stage": exc.item.stage},
                            "request_id": request.state.request_id}},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": str(exc), "request_id": request.state.request_id}},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed"
    codes = {401: "unauthorized", 403: "forbidden", 404: "not_found", 503: "service_unavailable"}
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": codes.get(exc.status_code, "http_error"), "message": detail,
                            "request_id": request.state.request_id}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    issues = [
        {"location": [str(part) for part in error.get("loc", ())], "message": error.get("msg", "Invalid value")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": "Request validation failed",
                            "issues": issues, "request_id": request.state.request_id}},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "constraint_conflict", "message": "The requested change conflicts with stored data",
                            "request_id": request.state.request_id}},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "database_unavailable", "message": "Platform storage is unavailable",
                            "request_id": request.state.request_id}},
    )

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "hyoga-nexus"}


@app.get("/api/v1/ready")
def ready():
    from sqlalchemy import text

    engine = getattr(app.state, "database_engine", None)
    if engine is None:
        try:
            engine = create_database_engine()
        except DatabaseConfigurationError:
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database_not_configured"})
        app.state.database_engine = engine
        app.state.session_factory = session_factory(engine)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database_unavailable"})
    return {"status": "ready", "database": "ok"}

@app.get("/api/v1/capabilities")
def capabilities():
    return {
        "runtimes": [{"name": "自研 Native", "status": "requires_configuration"},
                     *[{"name": name, "status": "planned"} for name in ["Codex", "Claude Code", "DeepSeek Harness"]]],
        "channels": [{"name": "Web", "status": "available"},
                     *[{"name": name, "status": "planned"} for name in ["企业微信", "微信", "QQ"]]],
        "applications": [{"name": "观澜 Guanlan", "status": "planned"}],
    }


@app.get("/api/v1/runtime-capabilities")
def runtime_capabilities():
    return {"native": {"status": "implemented", "configuration_required": True,
            "model_protocols": ["openai_chat_completions"], "streaming": True,
            "sequential_tools": True, "waiting_input": True, "cancellation": True,
            "working_checkpoint": True, "memory_drafts": True,
            "tools": ["ask_user", "update_working_checkpoint", "propose_memory_draft"]},
            "sandbox": {"status": "unavailable", "reason": "isolated_backend_not_configured",
                        "code_execution": False, "shell": False, "host_files": False,
                        "arbitrary_network": False, "file_artifacts": False}}
