"""
FastAPI app: POST /chat accepts user message, runs PydanticAI agent, returns reply.
CORS enabled for Shiny app. Loads OPENAI_API_KEY from env.
"""
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load .env from 5381 when running from hackathon
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .agent import run_chat
from .data_loader import ensure_loaded

app = FastAPI(title="NYC Urban Risk Chatbot API", version="1.0")


@app.on_event("startup")
def startup():
    try:
        ensure_loaded()
        logger.info("Data loaded successfully")
    except Exception as e:
        logger.error("Startup failed (data load): %s", e, exc_info=True)
        # Don't raise - app will start but /chat may fail


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Run the risk analyst agent on the user message and return the reply."""
    reply = run_chat(request.message)
    return ChatResponse(reply=reply)


@app.get("/")
def root() -> dict:
    return {
        "message": "NYC Urban Risk Chatbot API",
        "docs": "/docs",
        "health": "/health",
        "chat": "POST /chat",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("chatbot.main:app", host="0.0.0.0", port=8000, reload=False)
