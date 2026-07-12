"""FastAPI 应用入口"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.api.routers import router as api_router
from backend.config import settings, validate_security_settings
from backend.scheduler import start_scheduler, shutdown_scheduler
from backend.api.errors import http_exception_handler, validation_exception_handler, unhandled_exception_handler
from backend.middleware import ApiRateLimitMiddleware, RequestIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_settings()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    if settings.DATABASE_URL:
        logger.info(f"Database: PostgreSQL at {settings.DATABASE_URL}")
    else:
        logger.info("Database: SQLite (dev mode)")
    if settings.LLM_API_KEY:
        logger.info(f"LLM: {settings.LLM_MODEL} via {settings.LLM_API_BASE}")
    else:
        logger.warning("LLM API key not configured")
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Request IDs are added before rate limiting so rejected requests are traceable.
app.add_middleware(ApiRateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# CORS - 允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


app.include_router(api_router)

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def frontend_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not found. API docs are available at /docs."}


@app.get("/staff")
async def staff_frontend():
    staff_file = FRONTEND_DIR / "staff.html"
    if staff_file.exists():
        return FileResponse(staff_file)
    return {"message": "Staff frontend not found. API docs are available at /docs."}
