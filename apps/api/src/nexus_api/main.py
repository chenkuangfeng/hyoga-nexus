from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi.exceptions import RequestValidationError

from nexus_api.http.platform import router as platform_router
from nexus_platform.errors import PlatformError
from nexus_platform.configuration import DatabaseConfigurationError
from nexus_platform.persistence.database import create_database_engine, session_factory

app = FastAPI(title="Hyoga Nexus", version="0.1.0")
app.include_router(platform_router)
from nexus_api.http.model_settings import router as model_settings_router
app.include_router(model_settings_router)
from nexus_api.http.native import router as native_router
app.include_router(native_router)
from nexus_api.http.roles import router as roles_router
app.include_router(roles_router)
from nexus_api.http.auth import router as auth_router
app.include_router(auth_router)


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
