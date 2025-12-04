"""
Complete FastAPI wrapper for University RAG Chatbot
Run with: uvicorn api:app --reload --host 127.0.0.1 --port 5000
"""
import os
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from dotenv import load_dotenv

from chatbot import UniversityRAGChatbot
from main import AuthenticationManager
from configfile import EMBEDDINGS_FILE,CONFIG  # Import from your config file

# -----------------------------------
# Configuration
# -----------------------------------

logging.basicConfig(level=logging.INFO)
load_dotenv()

mongodb_config = CONFIG['mongodb']

# Global instances (initialized on startup)
chatbot: Optional[UniversityRAGChatbot] = None
auth_manager: Optional[object] = None

# Constants
FREE_QUERY_LIMIT = 2
sessions = {}  # In production, use Redis or database


# -----------------------------------
# Initialization Functions
# -----------------------------------

def initialize_chatbot() -> Optional[UniversityRAGChatbot]:
    """Initialize the RAG chatbot."""
    try:
        vector_store_path = os.getenv("VECTOR_STORE_PATH", EMBEDDINGS_FILE)
        gemini_api_key = os.getenv("GOOGLE_API_KEY")

        if not gemini_api_key:
            print("❌ GOOGLE_API_KEY not found in environment variables")
            print("💡 Set it in .env file or export GEMINI_API_KEY='your_key'")
            return None

        # Verify vector store exists
        if not Path(vector_store_path).exists():
            print(f"❌ Vector store not found at: {vector_store_path}")
            return None

        print(f"📂 Loading vector store from: {vector_store_path}")

        bot = UniversityRAGChatbot(
            vector_store_path=vector_store_path,
            gemini_api_key=gemini_api_key,
            top_k=10,
            fetch_k=20
        )

        return bot

    except Exception as e:
        logging.error(f"Failed to initialize chatbot: {e}")
        import traceback
        traceback.print_exc()
        return None


def initialize_auth():
    try:
        return AuthenticationManager(
            mongodb_config["host"],
            mongodb_config["database"]
        )
    except Exception as e:
        logging.error(f"Auth init failed: {e}")
        return None


# -----------------------------------
# Lifespan Management
# -----------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and cleanup on shutdown."""
    global chatbot, auth_manager

    print(" Initializing University RAG Chatbot API...")

    # Initialize chatbot
    chatbot = initialize_chatbot()
    if not chatbot:
        print(" Warning: Chatbot initialization failed")
    else:
        print(" Chatbot initialized successfully")

    # Initialize authentication
    auth_manager = initialize_auth()
    if not auth_manager:
        print("  Authentication disabled")
    else:
        print(" Authentication initialized successfully")

    yield

    # Cleanup (if needed)
    print(" Shutting down...")


# -----------------------------------
# FastAPI App
# -----------------------------------

app = FastAPI(
    title="University RAG Chatbot API",
    description="REST API for SRMIST University Chatbot",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------
# Request/Response Models
# -----------------------------------

class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: Optional[str] = None
    email: Optional[str] = None


class EmailRequest(BaseModel):
    """Request model for email submission."""
    email: EmailStr
    session_id: str


class SkipRequest(BaseModel):
    """Request model for skip email."""
    session_id: str


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    answer: str
    sources: Optional[str] = None
    session_id: str
    require_email: bool = False
    skip_count: Optional[int] = None


class EmailResponse(BaseModel):
    """Response model for email submission."""
    success: bool
    message: str
    session_id: Optional[str] = None


# -----------------------------------
# Helper Functions
# -----------------------------------

def get_or_create_session(session_id: str) -> dict:
    """Get or create a session."""
    if session_id not in sessions:
        sessions[session_id] = {
            "query_count": 0,
            "email_provided": False,
            "user_email": None,
            "skip_count": 0,
            "created_at": datetime.now().isoformat()
        }
    return sessions[session_id]


# -----------------------------------
# API Endpoints
# -----------------------------------

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "SRMIST University Chatbot API",
        "version": "1.0.0",
        "status": "online",
        "chatbot_ready": chatbot is not None,
        "endpoints": {
            "health": "/api/health",
            "chat": "/api/chat",
            "stream": "/api/chat/stream",
            "email_submit": "/api/email/submit",
            "email_skip": "/api/email/skip"
        },
        "docs": "/docs"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "chatbot_ready": chatbot is not None,
        "auth_enabled": auth_manager is not None,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming chat endpoint."""
    try:
        if not chatbot:
            raise HTTPException(
                status_code=503,
                detail="Chatbot is not initialized. Please check server logs."
            )

        message = request.message.strip()
        session_id = request.session_id or f"session_{datetime.now().timestamp()}"

        # Get or create session
        session = get_or_create_session(session_id)



        # Check if email is required (do NOT increment counter yet)
        if not session["email_provided"] and not request.email:
            # if we've already reached the free limit -> ask for email
            if session["query_count"] >= FREE_QUERY_LIMIT:
                return ChatResponse(
                    answer="",
                    sources=None,
                    session_id=session_id,
                    require_email=True,
                    skip_count=session["skip_count"]
                )

        # If email provided in request, save it (do not change query_count here)
        if request.email and not session["email_provided"]:
            session["email_provided"] = True
            session["user_email"] = request.email
            if auth_manager:
                auth_manager.save_email_only(request.email, session_id)

        # After successfully processing, increment the query counter (if email not provided)
        # NOTE: We increment after processing to avoid the skip/resend issue
        if not session["email_provided"]:
            session["query_count"] = session.get("query_count", 0) + 1

        # If email provided in request, save it
        if request.email and not session["email_provided"]:
            session["email_provided"] = True
            session["user_email"] = request.email
            if auth_manager:
                auth_manager.save_email_only(request.email, session_id)

        # Process query
        answer, sources = chatbot.query(message, stream=False)

        # Log query if auth manager available
        if auth_manager:
            auth_manager.log_query(
                student_id=None,
                query=message,
                response_length=len(answer),
                email=session.get("user_email"),
                session_id=session_id
            )

        return ChatResponse(
            answer=answer,
            sources=sources or "",
            session_id=session_id,
            require_email=False
        )

    except Exception as e:
        logging.error(f"Chat error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint using Server-Sent Events.
    Corrected email/query_count logic:
      - query_count is incremented AFTER a query is processed
      - Query3 (when query_count == FREE_QUERY_LIMIT) asks for email but allows SKIP
      - Query4 (query_count >= FREE_QUERY_LIMIT + 1) requires email and NO skip
      - If email is provided in the request, save and continue processing
    """
    try:
        if not chatbot:
            raise HTTPException(
                status_code=503,
                detail="Chatbot is not initialized"
            )

        message = request.message.strip()
        session_id = request.session_id or f"session_{datetime.now().timestamp()}"

        # Get or create session
        session = get_or_create_session(session_id)

        qc = session["query_count"]
        email_provided = session["email_provided"]
        skip_used = session.get("skip_count", 0)

        # ---------- Email already provided: allow processing ----------
        if email_provided:
            # proceed to processing below
            pass

        else:
            # ---------- Query 1 & 2: allow ----------
            if qc < FREE_QUERY_LIMIT:
                pass

            # ---------- Query 4+: require email, NO skip ----------

            elif qc == FREE_QUERY_LIMIT:
                # If skip was already used, allow processing of the blocked query.
                # skip_used == 0  -> user hasn't skipped yet (show skip button)
                # skip_used == 1  -> user already used skip -> allow the resend to proceed
                skip_allowed = (skip_used == 0)

                # If client did not include email in this request:
                if not request.email:
                    # If skip was already used, allow processing (frontend will have called /api/email/skip)
                    if skip_used == 1:
                        # allow processing (do not block) — continue to processing below
                        pass
                    else:
                        # No skip used yet — ask for email and allow skip on frontend
                        async def stop_event():
                            data = {
                                "require_email": True,
                                "message": "You've reached the free query limit. Please provide your email to continue.",
                                "skip_allowed": skip_allowed,
                                "skip_count": skip_used,
                                "session_id": session_id,
                                "done": True
                            }
                            yield f"data: {json.dumps(data)}\n\n"

                        return StreamingResponse(
                            stop_event(),
                            media_type="text/event-stream",
                            headers={
                                "Cache-Control": "no-cache",
                                "X-Accel-Buffering": "no",
                                "Connection": "keep-alive"
                            }
                        )

                # If email was included, save it and continue
                if request.email:
                    session["email_provided"] = True
                    session["user_email"] = request.email
                    session["skip_count"] = 0

            else:  # qc >= FREE_QUERY_LIMIT + 1
                if not request.email:
                    async def stop_event():
                        data = {
                            "require_email": True,
                            "message": "Email is required to continue.",
                            "skip_allowed": False,
                            "skip_count": skip_used,
                            "session_id": session_id,
                            "done": True
                        }
                        yield f"data: {json.dumps(data)}\n\n"
                    return StreamingResponse(
                        stop_event(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no",
                            "Connection": "keep-alive"
                        }
                    )

                # If email included, save it and continue
                else:
                    session["email_provided"] = True
                    session["user_email"] = request.email
                    session["skip_count"] = 0

        # ---------- PROCESS QUERY (stream results) ----------
        async def generate():
            try:
                accumulated_answer = ""
                sources = ""

                # Stream from chatbot (assumes chatbot.query yields dicts)
                for chunk in chatbot.query(message, stream=True):
                    partial_answer = chunk.get("content", "")
                    partial_sources = chunk.get("sources", "")
                    done = chunk.get("done", False)

                    if partial_answer:
                        accumulated_answer = partial_answer
                    if partial_sources:
                        sources = partial_sources

                    event_data = {
                        "content": partial_answer,
                        "sources": partial_sources or "",
                        "done": done
                    }
                    yield f"data: {json.dumps(event_data)}\n\n"

                # After fully processed — increment query_count
                # (Important: increment AFTER processing so skip/resend flows work)
                session["query_count"] = session.get("query_count", 0) + 1
                # session["skip_count"] = 1

                final_data = {
                    "content": accumulated_answer,
                    "sources": sources,
                    "done": True,
                    "session_id": session_id
                }
                yield f"data: {json.dumps(final_data)}\n\n"

                # Optional: logging via auth_manager if present
                if auth_manager:
                    auth_manager.log_query(
                        student_id=None,
                        query=message,
                        response_length=len(accumulated_answer),
                        email=session.get("user_email"),
                        session_id=session_id
                    )

            except Exception as e:
                logging.error(f"Streaming error: {e}")
                error_data = {
                    "error": str(e),
                    "done": True
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )

    except Exception as e:
        logging.error(f"Stream setup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/submit", response_model=EmailResponse)
async def submit_email(request: EmailRequest):
    """Submit email to continue chatting."""
    try:
        session_id = request.session_id

        if not session_id or session_id not in sessions:
            raise HTTPException(status_code=400, detail="Invalid session")

        session = sessions[session_id]
        session["email_provided"] = True
        session["user_email"] = request.email
        session["skip_count"] = 0  # reset skip since email provided

        # Do NOT reset query_count; we want correct ordering and counting
        if auth_manager:
            result = auth_manager.save_email_only(request.email, session_id)
            if result and not result.get("success", True):
                raise HTTPException(
                    status_code=400,
                    detail=result.get("message", "Failed to save email")
                )

        return EmailResponse(
            success=True,
            message="Email saved successfully",
            session_id=session_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Email submission error: {e}")
        raise HTTPException(status_code=500, detail="Error saving email")

@app.post("/api/email/skip", response_model=EmailResponse)
async def skip_email(request: SkipRequest):
    """Skip email submission (allowed only for Query 3 and only once)."""
    try:
        session_id = request.session_id

        if not session_id or session_id not in sessions:
            raise HTTPException(status_code=400, detail="Invalid session")

        session = sessions[session_id]
        # Only allow skip when query_count == FREE_QUERY_LIMIT (Query 3)
        if session.get("query_count", 0) != FREE_QUERY_LIMIT:
            return EmailResponse(
                success=False,
                message="Skip not allowed at this stage.",
                session_id=session_id
            )

        if session.get("skip_count", 0) >= 1:
            return EmailResponse(
                success=False,
                message="Skip already used.",
                session_id=session_id
            )

        # Mark skip used — DO NOT increment query_count here.
        session["skip_count"] = 1

        return EmailResponse(
            success=True,
            message="Skip accepted. Please wait while we process your previous question.",
            session_id=session_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Skip email error: {e}")
        raise HTTPException(status_code=500, detail="Error processing request")

@app.post("/api/session/clear")
async def clear_session(request: SkipRequest):
    """Clear a session."""
    try:
        session_id = request.session_id

        if session_id in sessions:
            del sessions[session_id]

        return {
            "success": True,
            "message": "Session cleared"
        }

    except Exception as e:
        logging.error(f"Clear session error: {e}")
        raise HTTPException(status_code=500, detail="Error clearing session")


# -----------------------------------
# Run Server
# -----------------------------------

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print(" SRMIST University Chatbot API")
    print("=" * 60)
    print("📍 Server: http://localhost:8000")
    print("📚 Docs: http://localhost:8000/docs")
    print("🔧 Health: http://localhost:8000/api/health")
    print("=" * 60)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        reload=True  # Auto-reload on code changes
    )