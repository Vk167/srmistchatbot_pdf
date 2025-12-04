"""
Main application entry point for University RAG Chatbot
"""
import os
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime
import re

from chatbot import UniversityRAGChatbot
from UI import create_gradio_interface

from configfile import CONFIG

mongodb_config = CONFIG['mongodb']

# -----------------------------------
# Configuration
# -----------------------------------

logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Try to import config with error handling
try:
    from configfile import CONFIG, EMBEDDINGS_FILE

    rag_config = CONFIG["ragchatbot"]
    embedding_config = CONFIG["embedding"]
    mongodb_config = CONFIG["mongodb"]

    VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", EMBEDDINGS_FILE)

except ImportError:
    print(" Warning: configfile.py not found. Using default settings.")
    rag_config = {"top_k": 10, "model_name": "models/gemini-2.0-flash"}
    embedding_config = {"model_name": "all-MiniLM-L6-v2"}
    mongodb_config = {
        "host": os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
        "database": "university_chatbot"
    }
    VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", "./vector_store")


# API Keys
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")


# -----------------------------------
# Authentication & Logging Manager
# -----------------------------------

class AuthenticationManager:
    """Minimal manager: store email for anonymous users + log usage."""

    def __init__(self, mongodb_config: str, db_name: str):
        try:
            self.client = MongoClient(mongodb_config)
            self.db = self.client[db_name]

            # Collections
            self.email_only_users = self.db.email_only_users
            self.usage_logs = self.db.usage_logs

            # Indexes
            self.email_only_users.create_index("email")
            self.email_only_users.create_index("session_id")

            print(" Authentication/Logging manager initialized successfully")

        except Exception as e:
            logging.error(f"Failed to initialize authentication/logging: {str(e)}")
            raise

    def validate_email(self, email: str) -> bool:
        """Validate email format."""
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, email.lower()))

    def save_email_only(self, email: str, session_id: str) -> dict:
        """Save user email for anonymous users."""
        try:
            if not self.validate_email(email):
                return {"success": False, "message": "Invalid email format"}

            email_lower = email.lower()
            existing = self.email_only_users.find_one({"email": email_lower})

            if existing:
                self.email_only_users.update_one(
                    {"email": email_lower},
                    {
                        "$set": {
                            "last_used": datetime.utcnow(),
                            "session_id": session_id
                        },
                        "$inc": {"total_queries": 1},
                    },
                )
            else:
                self.email_only_users.insert_one(
                    {
                        "email": email_lower,
                        "created_at": datetime.utcnow(),
                        "last_used": datetime.utcnow(),
                        "total_queries": 1,
                        "session_id": session_id,
                    }
                )

            return {"success": True, "message": "Email saved successfully"}

        except Exception as e:
            logging.error(f"Email save error: {str(e)}")
            return {"success": False, "message": "Failed to save email"}

    def log_query(
            self,
            student_id: Optional[str],
            query: str,
            response_length: int = 0,
            email: Optional[str] = None,
            session_id: Optional[str] = None,
    ):
        """Log user queries (for monitoring and cost tracking)."""
        try:
            log_data = {
                "student_id": student_id,
                "email": email,
                "session_id": session_id,
                "query": query[:500],
                "query_length": len(query),
                "response_length": response_length,
                "timestamp": datetime.utcnow(),
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
            }

            self.usage_logs.insert_one(log_data)

        except Exception as e:
            logging.error(f"Query logging error: {str(e)}")


# -----------------------------------
# Initialization Helpers
# -----------------------------------

def initialize_chatbot() -> Optional[UniversityRAGChatbot]:
    """
    Initialize the RAG chatbot.

    Returns:
        UniversityRAGChatbot instance or None if initialization fails
    """
    try:
        if not GEMINI_API_KEY:
            print(" Error: GOOGLE_API_KEY environment variable not set")
            return None

        if not Path(VECTOR_STORE_PATH).exists():
            print(f" Error: Vector store path does not exist: {VECTOR_STORE_PATH}")
            return None

        # Prepare LLM config
        llm_config = {
            "model_name": rag_config.get("model_name", "models/gemini-2.0-flash"),
            "max_output_tokens": 8192,
            "temperature": 0.7,
            "top_p": 0.95,
            "max_retries": 3
        }

        return UniversityRAGChatbot(
            vector_store_path=VECTOR_STORE_PATH,
            gemini_api_key=GEMINI_API_KEY,
            embedding_model=embedding_config.get("model_name", "all-MiniLM-L6-v2"),
            llm_config=llm_config,
            top_k=rag_config.get("top_k", 10),
            fetch_k=20
        )

    except Exception as e:
        logging.error(f"Chatbot initialization failed: {str(e)}")
        return None


def initialize_auth() -> Optional[AuthenticationManager]:
    """
    Initialize the authentication manager.

    Returns:
        AuthenticationManager instance or None if initialization fails
    """
    try:
        return AuthenticationManager(
            mongodb_config["host"],
            mongodb_config["database"]
        )
    except Exception as e:
        logging.error(f"Authentication initialization failed: {str(e)}")
        return None


# -----------------------------------
# Main
# -----------------------------------

def main():
    """Main application entry point."""
    try:
        print("=" * 60)
        print(" Starting University RAG Chatbot...")
        print("=" * 60)

        # Initialize chatbot
        print("\n Initializing chatbot...")
        chatbot = initialize_chatbot()
        if not chatbot:
            print(" Chatbot initialization failed")
            return

        # Initialize authentication
        print("\n Initializing authentication...")
        auth_manager = initialize_auth()
        if not auth_manager:
            print("  Authentication/logging initialization failed")
            print("   Continuing without authentication features...")
            auth_manager = None

        print("\n" + "=" * 60)
        print(" All systems initialized successfully")
        print("=" * 60)

        # Create and launch UI
        print("\n Launching Gradio interface...")
        interface = create_gradio_interface(chatbot, auth_manager)

        interface.launch(
            share=True,
            debug=True,
            show_error=True,
        )

    except Exception as e:
        logging.error(f"Failed to launch interface: {str(e)}")
        print(f"\n Error launching interface: {str(e)}")


if __name__ == "__main__":
    main()