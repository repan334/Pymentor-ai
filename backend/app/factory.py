from fastapi import FastAPI

from app.api.middleware import JsonBodyLimitMiddleware, MultipartBodyLimitMiddleware
from app.api.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API without connecting to external services or mutating state."""
    selected_settings = settings or get_settings()
    application = FastAPI(
        title=selected_settings.app_name,
        version="0.1.0",
        debug=selected_settings.app_debug,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    application.state.settings = selected_settings
    application.include_router(api_router, prefix=selected_settings.api_v1_prefix)
    documents_path = f"{selected_settings.api_v1_prefix}/documents"
    application.add_middleware(
        MultipartBodyLimitMiddleware,
        path=documents_path,
        max_bytes=selected_settings.max_multipart_body_size_bytes,
    )
    application.add_middleware(
        JsonBodyLimitMiddleware,
        exclude_paths=(documents_path,),
        max_bytes=selected_settings.max_json_body_size_bytes,
    )
    return application
