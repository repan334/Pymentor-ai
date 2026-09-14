from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.quizzes import router as quizzes_router
from app.api.routes.retrieval import router as retrieval_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(retrieval_router)
api_router.include_router(chat_router)
api_router.include_router(quizzes_router)
