from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.features.rag.api.admin import router as admin_router
from app.features.rag.api.inspect import router as rag_inspect_router
from app.shared.api.auth import router as auth_router
from app.features.chat.api.chat import router as chat_router
from app.features.knowledge_bases.api.files import router as files_router
from app.shared.api.health import router as health_router
from app.features.knowledge_bases.api.knowledge_bases import router as knowledge_bases_router
from app.shared.api.llm_info import router as llm_info_router
from app.features.slides.api.slide_sessions import router as slide_sessions_router
from app.core.config import get_settings
from app.startup import lifespan


def create_app() -> FastAPI:
    app = FastAPI(title="KnowledgeDeck API", version="0.1.0", lifespan=lifespan)

    origins = get_settings().cors_origins_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(knowledge_bases_router)
    app.include_router(files_router)
    app.include_router(chat_router)
    app.include_router(slide_sessions_router)
    app.include_router(llm_info_router)
    app.include_router(admin_router)
    app.include_router(rag_inspect_router)
    return app


app = create_app()
