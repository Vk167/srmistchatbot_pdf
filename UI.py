"""
Gradio UI for University RAG Chatbot
"""
import logging
from typing import Tuple
from datetime import datetime

import gradio as gr

# Constants
FREE_QUERY_LIMIT = 2


def create_email_prompt_html() -> str:
    """HTML card shown inside the chatbot when query limit is reached."""
    return """
<div class="email-card" style="background-color:#fff9e6; border:2px solid #ffc107; border-radius:10px; padding:16px; margin:10px 0; font-size:14px;">
  <div style="font-weight:bold; margin-bottom:8px; color:#d9534f;">
     Query limit reached
  </div>
  <div style="margin-bottom:10px; color:#555;">
    You've used your free queries. Please enter your email to continue chatting.
  </div>
  <input
    type="email"
    class="email-input-field"
    placeholder="your.email@example.com"
    style="width:100%; padding:10px; border:1px solid #ccc; border-radius:5px; font-size:14px; box-sizing:border-box; margin-bottom:10px;"
  />
  <div style="display:flex; gap:10px; margin-bottom:6px;">
    <button
      type="button"
      class="email-submit-btn"
      style="flex:1; padding:10px; border:none; border-radius:5px; cursor:pointer; font-weight:600; background-color:#007bff; color:white;"
    >
      Submit Email
    </button>
    <button
      type="button"
      class="email-skip-btn"
      style="flex:1; padding:10px; border:none; border-radius:5px; cursor:pointer; background-color:#6c757d; color:white;"
    >
      Maybe Later
    </button>
  </div>
  <div style="font-size:12px; color:#777; text-align:center;">
    Your email helps us improve the service
  </div>
</div>
"""


def create_gradio_interface(chatbot, auth_manager):
    """
    Create Gradio UI for the chatbot.

    Args:
        chatbot: UniversityRAGChatbot instance
        auth_manager: AuthenticationManager instance

    Returns:
        Gradio Blocks interface
    """

    # Session state
    current_session = {
        "query_count": 0,
        "email_provided": False,
        "user_email": None,
        "session_id": None,
        "skip_count": 0,
        "pending_message": None,
    }

    def submit_email(email: str) -> Tuple[str, bool]:
        """Handle email submission from anonymous users."""
        if not auth_manager:
            return "Email system unavailable", False

        if not email or not email.strip():
            return "Please enter a valid email address", False

        if not current_session.get("session_id"):
            current_session["session_id"] = f"session_{datetime.now().timestamp()}"

        result = auth_manager.save_email_only(email, current_session["session_id"])

        if result["success"]:
            current_session["email_provided"] = True
            current_session["user_email"] = email
            return " ", True
        else:
            return f" {result['message']}", False

    def run_query(message: str, history: list, as_pending: bool = False):
        """
        Call RAG chatbot and append response.

        Args:
            message: User message
            history: Chat history
            as_pending: If True, only bot message (user question already shown)

        Yields:
            Updated history for streaming
        """
        if not chatbot:
            history.append(
                [message, "Chatbot is not initialized. Please restart the application."]
            )
            yield history
            return

        try:
            accumulated_answer = ""
            sources = ""
            first_chunk = True

            # Stream the response
            for partial_answer, partial_sources in chatbot.query(message, stream=True):
                accumulated_answer = partial_answer
                sources = partial_sources

                # Update history with current accumulated answer
                if as_pending:
                    if first_chunk:
                        history.append(["", accumulated_answer])
                        first_chunk = False
                    else:
                        history[-1] = ["", accumulated_answer]
                else:
                    if first_chunk:
                        history.append([message, accumulated_answer])
                        first_chunk = False
                    else:
                        history[-1] = [message, accumulated_answer]

                yield history

            # Add sources at the end if available
            if sources:
                bot_response = f"{accumulated_answer}\n\n{sources}"
                if as_pending:
                    history[-1] = ["", bot_response]
                else:
                    history[-1] = [message, bot_response]
                yield history

            # Log the query
            if auth_manager:
                auth_manager.log_query(
                    student_id=None,
                    query=message,
                    response_length=len(accumulated_answer),
                    email=current_session.get("user_email"),
                    session_id=current_session.get("session_id"),
                )

        except Exception as e:
            logging.error(f"Chat error: {str(e)}")
            import traceback
            traceback.print_exc()
            bot_response = (
                "I encountered an error processing your question. Please try again."
            )

            if as_pending:
                history.append(["", bot_response])
            else:
                history.append([message, bot_response])

            yield history

    def process_normal_message(message: str, history: list):
        """
        Handle normal user questions with free limit + email logic.

        Yields:
            Empty message input and updated history
        """
        # Ensure session id
        if not current_session.get("session_id"):
            current_session["session_id"] = f"session_{datetime.now().timestamp()}"

        # If email already given, no limit
        if current_session.get("email_provided"):
            for updated_history in run_query(message, history, as_pending=False):
                yield "", updated_history
            return

        # Increment free query count
        current_session["query_count"] += 1

        # Within free query limit
        if current_session["query_count"] <= FREE_QUERY_LIMIT:
            for updated_history in run_query(message, history, as_pending=False):
                yield "", updated_history
            return

        # Over limit → ask for email, store pending message
        current_session["pending_message"] = message
        email_card = create_email_prompt_html()
        history.append([message, email_card])
        yield "", history

    def handle_email_submission(message: str, history: list):
        """Handle EMAIL_SUBMIT:<email> from inline HTML button."""
        email = message.replace("EMAIL_SUBMIT:", "").strip()
        status_msg, success = submit_email(email)

        if success:
            pending = current_session.get("pending_message")
            current_session["pending_message"] = None
            current_session["email_provided"] = True
            current_session["skip_count"] = 0

            if pending:
                # Stream the pending query response
                for updated_history in run_query(pending, history, as_pending=True):
                    yield "", updated_history
            else:
                yield "", history
        else:
            # Show error + prompt again
            error_text = f"{status_msg}\n\n{create_email_prompt_html()}"
            history.append([" Email Submission", error_text])
            yield "", history

    def handle_skip_email(history: list):
        """Handle SKIP_EMAIL from 'Maybe Later'."""
        pending = current_session.get("pending_message")

        if not pending:
            history.append(["", "There is no pending question to process."])
            yield "", history
            return

        skip_count = current_session.get("skip_count", 0)

        if skip_count == 0:
            # First Maybe Later → process pending, don't save email
            current_session["skip_count"] = 1
            current_session["pending_message"] = None

            # Stream the response
            for updated_history in run_query(pending, history, as_pending=True):
                yield "", updated_history
        else:
            # Second Maybe Later → email mandatory, do NOT process
            warning = "️ Email is now required to continue. Please enter your email below."
            history.append(["", warning + "\n\n" + create_email_prompt_html()])
            yield "", history

    def chat_handler(message: str, history: list):
        """Main chat handler - supports streaming."""
        if history is None:
            history = []

        if not message or not message.strip():
            yield "", history
            return

        # Special commands from inline HTML buttons
        if message.startswith("EMAIL_SUBMIT:"):
            for result in handle_email_submission(message, history):
                yield result
            return

        if message == "SKIP_EMAIL":
            for result in handle_skip_email(history):
                yield result
            return

        # Normal user question - stream the response
        for result in process_normal_message(message, history):
            yield result

    def clear_history():
        """Clear chat history."""
        return []

    # CSS styling
    css = """
    .gradio-container {
        font-family: 'Segoe UI', sans-serif;
        max-width: 1000px;
        margin: auto;
        padding: 0 10px;
    }
    .chat-container {
        display: flex;
        flex-direction: column;
        height: calc(100vh - 150px);
    }
    #chatbot {
        flex-grow: 1;
        overflow-y: auto;
        border: 1px solid #ccc;
        border-radius: 8px;
        background-color: #f9f9f9;
        padding: 8px;
    }
    """

    # Build interface
    with gr.Blocks(css=css, title="University Chatbot") as interface:
        gr.HTML("<h1 style='text-align:center;'> SRMIST University Assistant</h1>")
        gr.HTML(
            "<p style='text-align:center; color:#666;'>"
            "Ask me anything about the university!</p>"
        )

        chatbot_ui = gr.Chatbot(
            elem_id="chatbot",
            elem_classes="chat-container",
            height=500
        )

        # Chat input & buttons
        with gr.Row():
            msg_input = gr.Textbox(
                placeholder="Type your question here...",
                lines=1,
                scale=8,
                show_label=False,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)

        clear_btn = gr.Button("Clear Chat", size="sm")

        gr.HTML(
            "<div style='text-align:center; font-size:12px; margin-top:6px; color:#666;'>"
            " SRMIST Chatbot is experimental & accuracy might vary</div>"
        )
        gr.HTML(
            "<div style='text-align:center; margin-top:10px; color:#666;'>"
            "Developed by SRMTech | Built for SRMIST University</div>"
        )

        # Bind events
        send_btn.click(
            chat_handler,
            inputs=[msg_input, chatbot_ui],
            outputs=[msg_input, chatbot_ui],
        )

        msg_input.submit(
            chat_handler,
            inputs=[msg_input, chatbot_ui],
            outputs=[msg_input, chatbot_ui],
        )

        clear_btn.click(clear_history, outputs=[chatbot_ui])

        # JavaScript for inline email buttons
        interface.load(
            None,
            None,
            None,
            js="""
            function() {
                document.addEventListener('click', function(e) {
                    const t = e.target;
                    if (!t) return;

                    // Submit Email
                    if (t.classList.contains('email-submit-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const card = t.closest('.email-card');
                        const emailInput = card ? card.querySelector('.email-input-field') : null;
                        if (emailInput && emailInput.value) {
                            const msgInput = document.querySelector('textarea[placeholder="Type your question here..."]');
                            if (msgInput) {
                                msgInput.value = 'EMAIL_SUBMIT:' + emailInput.value;
                                msgInput.dispatchEvent(new Event('input', {bubbles: true}));
                                setTimeout(() => {
                                    const sendBtn = Array.from(document.querySelectorAll('button'))
                                        .find(b => b.textContent.trim() === 'Send');
                                    if (sendBtn) sendBtn.click();
                                }, 50);
                            }
                        }
                        return false;
                    }

                    // Maybe Later
                    if (t.classList.contains('email-skip-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const msgInput = document.querySelector('textarea[placeholder="Type your question here..."]');
                        if (msgInput) {
                            msgInput.value = 'SKIP_EMAIL';
                            msgInput.dispatchEvent(new Event('input', {bubbles: true}));
                            setTimeout(() => {
                                const sendBtn = Array.from(document.querySelectorAll('button'))
                                    .find(b => b.textContent.trim() === 'Send');
                                if (sendBtn) sendBtn.click();
                            }, 50);
                        }
                        return false;
                    }
                }, true);
            }
            """,
        )

    return interface