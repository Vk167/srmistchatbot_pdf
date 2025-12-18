"""
University RAG Chatbot core functionality - FIXED VERSION
"""
import re
import json
import random
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Generator
from datetime import datetime

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

from llm_config import setup_gemini_llm
from prompts import get_rag_prompt, GREETING_RESPONSES, GREETING_KEYWORDS


class UniversityRAGChatbot:
    """University RAG Chatbot using Google Gemini + FAISS"""

    def __init__(
            self,
            vector_store_path: str,
            gemini_api_key: str,
            embedding_model: str = "all-MiniLM-L6-v2",
            llm_config: dict = None,
            top_k: int = 10,
            fetch_k: int = 20
    ):
        """Initialize the RAG chatbot."""
        try:
            if not gemini_api_key:
                raise ValueError("Gemini API key is required")

            if not vector_store_path:
                raise ValueError("Vector store path is required")

            if not Path(vector_store_path).exists():
                raise FileNotFoundError(
                    f"Vector store path does not exist: {vector_store_path}"
                )

            print("Initializing University RAG Chatbot with Google Gemini...")

            self.top_k = top_k
            self.fetch_k = fetch_k

            # Initialize components
            self.setup_embeddings(embedding_model)
            self.load_vector_store(vector_store_path)
            self.llm = setup_gemini_llm(gemini_api_key, llm_config)
            self.setup_retrieval_chain()

            print("✅ Chatbot ready!")

        except Exception as e:
            logging.error(f"Failed to initialize chatbot: {str(e)}")
            raise

    def setup_embeddings(self, model_name: str):
        """Load embedding model."""
        try:
            print("Loading embedding model...")
            self.embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            print("✅ Embedding model loaded successfully")
        except Exception as e:
            logging.error(f"Failed to load embedding model: {str(e)}")
            raise RuntimeError(f"Could not load embedding model: {str(e)}")

    def load_vector_store(self, vector_store_path: str):
        """Load FAISS vector store."""
        try:
            print(f"Loading vector store from: {vector_store_path}")
            self.vector_store = FAISS.load_local(
                vector_store_path,
                self.embeddings,
                allow_dangerous_deserialization=True,
            )
            print(
                f"✅ Loaded vector store with {self.vector_store.index.ntotal} documents"
            )
        except Exception as e:
            logging.error(f"Failed to load vector store: {str(e)}")
            raise RuntimeError(f"Could not load vector database: {str(e)}")

    def setup_retrieval_chain(self):
        """Setup document retriever."""
        try:
            print("Setting up retrieval chain...")
            self.retriever = self.vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": self.top_k, "fetch_k": self.fetch_k},
            )
            print("✅ Retrieval chain configured successfully")
        except Exception as e:
            logging.error(f"Failed to setup retrieval chain: {str(e)}")
            raise RuntimeError(f"Could not setup retrieval chain: {str(e)}")

    def _build_structured_context(self, docs: list) -> str:
        """Build structured context from retrieved documents."""
        context_parts = []
        seen_content = set()

        for doc in docs:
            content = doc.page_content.strip()
            if content in seen_content:
                continue
            seen_content.add(content)

            chunk_type = doc.metadata.get("chunk_type", "")

            if chunk_type == "table_complete":
                context_parts.append(
                    f"\n=== TABLE DATA START ===\n{content}\n=== TABLE DATA END ===\n"
                )
            elif chunk_type in ("section_h1", "section_h2"):
                context_parts.append(f"\n## {content}\n")
            else:
                # Check if content has key:value pairs (likely table data)
                if ":" in content and any(
                        key in content
                        for key in [
                            "Degree", "Fees", "Branch", "Duration", "Room Type",
                            "Hostel", "Fee", "Annual", "Sharing"
                        ]
                ):
                    context_parts.append(f"\n[TABLE ROW DATA]\n{content}\n[END TABLE ROW]\n")
                else:
                    context_parts.append(content)

        return "\n\n".join(context_parts)

    def _filter_relevant_documents(self, docs, question: str) -> list:
        """Filter and limit retrieved documents."""
        if not docs:
            return []
        return docs[: min(self.top_k, len(docs))]

    def _handle_no_relevant_docs(self, question: str) -> Tuple[str, str]:
        """Handle cases where no relevant documents are found."""
        if "event" in question.lower() or "upcoming" in question.lower():
            return (
                "I don't have current information about upcoming events in my database. "
                "Please check the university's official website or contact the student "
                "affairs office for the latest event schedule.",
                "",
            )

        return (
            "I don't have specific information about that topic in my database. "
            "Could you please rephrase your question or ask about something more "
            "specific to the university?",
            "",
        )

    def _should_show_sources(
            self, answer: str, context: str, docs: list, question: str
    ) -> bool:
        """Determine whether to show sources based on answer type."""
        answer_lower = answer.lower()
        question_lower = question.lower()

        # Always show sources if answer indicates uncertainty
        uncertainty_indicators = [
            "i don't have", "not available", "i cannot find",
            "not enough information", "limited information",
            "don't have current information", "check the university",
            "please contact", "i'm not sure", "unable to find"
        ]

        if any(indicator in answer_lower for indicator in uncertainty_indicators):
            return True

        # Always show sources for factual/important queries
        important_topics = [
            "fee", "fees", "cost", "price", "tuition",
            "admission", "eligibility", "requirement", "apply",
            "deadline", "last date", "due date",
            "scholarship", "financial aid",
            "hostel", "accommodation", "mess",
            "placement", "internship", "job",
            "contact", "email", "phone", "address",
            "course", "curriculum", "syllabus", "program",
            "exam", "schedule", "timetable", "calendar",
        ]

        if any(topic in question_lower for topic in important_topics):
            return True

        # Show sources for detailed responses
        if len(answer) > 500:
            return True

        # Show sources if answer contains specific data
        specific_data_indicators = [
            "₹", "rupees", "inr", "rs.",
            "@", ".com", ".in", ".edu",
            "phone:", "tel:", "contact:",
            "deadline:", "last date:",
            "eligibility:", "requirement:",
        ]

        if any(indicator in answer_lower for indicator in specific_data_indicators):
            return True

        # Don't show sources for conversational responses
        conversational_indicators = [
            "hi there", "hello", "how can i help", "feel free to ask",
            "anything else", "you're welcome", "glad to help", "happy to assist"
        ]

        if any(indicator in answer_lower for indicator in conversational_indicators):
            return False

        # Don't show sources for very short answers without facts
        if len(answer) < 100:
            if any(char.isdigit() for char in answer):
                return True
            return False

        # Show sources if we have good quality documents
        if len(docs) >= 2 and len(context) > 300:
            return True

        return False

    def _format_sources(self, docs: list) -> str:
        """Format source citations."""
        if not docs:
            return ""

        # Score and rank documents
        scored_docs = []
        for doc in docs:
            score = 0
            title = doc.metadata.get("title", "")
            url = doc.metadata.get("url") or doc.metadata.get("source", "")

            if "srmist" in title.lower() or "srmist" in url.lower():
                score += 2

            if len(title) > 20 and title != "University Information":
                score += 1

            if len(doc.page_content) > 500:
                score += 1

            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)

        # Select 1-3 top sources
        num_sources = min(3, len(scored_docs))
        selected_docs = [doc for score, doc in scored_docs[:num_sources]]

        sources_info = "\n\n \n"
        for i, doc in enumerate(selected_docs, 1):
            title = doc.metadata.get("title", "University Information")
            source_url = doc.metadata.get("url", "")

            if source_url and source_url != "Unknown":
                if len(title) > 60:
                    title = title[:57] + "..."
                sources_info += f"{i}. [{title}]({source_url})\n"

        return sources_info

    def _parse_and_format_response(self, raw_response: str) -> str:
        """Parse LLM response and extract clean format."""
        # Extract Markdown table if present
        markdown_match = re.search(
            r'<<MARKDOWN_TABLE>>(.*?)<<END_MARKDOWN_TABLE>>',
            raw_response,
            re.DOTALL
        )

        if markdown_match:
            markdown_table = markdown_match.group(1).strip()
            cleaned = re.sub(
                r'<<TABLE_JSON>>.*?<<END_TABLE_JSON>>',
                '',
                raw_response,
                flags=re.DOTALL
            )
            cleaned = re.sub(
                r'<<MARKDOWN_TABLE>>.*?<<END_MARKDOWN_TABLE>>',
                markdown_table,
                cleaned,
                flags=re.DOTALL
            )
            return cleaned.strip()

        # Try to extract and render JSON as markdown
        json_match = re.search(
            r'<<TABLE_JSON>>(.*?)<<END_TABLE_JSON>>',
            raw_response,
            re.DOTALL
        )

        if json_match:
            try:
                json_str = json_match.group(1).strip()
                table_data = json.loads(json_str)

                headers = table_data.get('headers', [])
                rows = table_data.get('rows', [])

                # Build markdown table
                markdown = "\n| " + " | ".join(headers) + " |\n"
                markdown += "|" + "|".join(["---" for _ in headers]) + "|\n"

                for row in rows:
                    formatted_row = [
                        str(cell) if cell is not None else "" for cell in row
                    ]
                    markdown += "| " + " | ".join(formatted_row) + " |\n"

                cleaned = re.sub(
                    r'<<TABLE_JSON>>.*?<<END_TABLE_JSON>>',
                    markdown,
                    raw_response,
                    flags=re.DOTALL
                )
                return cleaned.strip()

            except json.JSONDecodeError:
                pass

        # Remove any leftover markers
        cleaned = raw_response
        cleaned = re.sub(r'<<MARKDOWN_TABLE>>', '', cleaned)
        cleaned = re.sub(r'<<END_MARKDOWN_TABLE>>', '', cleaned)
        cleaned = re.sub(r'<<TABLE_JSON>>.*?<<END_TABLE_JSON>>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'<<([^>]*)>>', '', cleaned)  # Remove any remaining markers

        return cleaned.strip()

    def query(self, question: str, stream: bool = False):
        """
        Main RAG query method.

        Args:
            question: User question
            stream: If True, yields response chunks for streaming

        Returns:
            If stream=False: Tuple[str, str] (answer, sources)
            If stream=True: Generator yielding dict with 'content' and 'sources'
        """
        if stream:
            return self._query_streaming(question)
        else:
            return self._query_non_streaming(question)

    def _query_non_streaming(self, question: str) -> Tuple[str, str]:
        """Non-streaming query - returns tuple directly."""
        try:
            if not question or not question.strip():
                return "Please ask a question about the university.", ""

            if len(question) > 1000:
                return "Please keep your questions under 1000 characters.", ""

            q_lower = question.lower()

            # Handle date/time queries
            if any(phrase in q_lower for phrase in [
                "what is the date", "what's the date", "current date",
                "today's date", "what date is it"
            ]):
                current_date = datetime.now().strftime("%A, %B %d, %Y")
                return f"Today's date is {current_date}.", ""

            if any(phrase in q_lower for phrase in [
                "what time", "current time", "what's the time"
            ]):
                current_time = datetime.now().strftime("%I:%M %p")
                return f"The current time is {current_time}.", ""

            # Handle greetings
            is_greeting = (
                    any(g in q_lower for g in GREETING_KEYWORDS)
                    and len(question.split()) <= 3
            )
            if is_greeting:
                return random.choice(GREETING_RESPONSES), ""

            # Retrieve relevant documents
            try:
                relevant_docs = self.retriever.get_relevant_documents(question)
            except Exception as e:
                logging.error(f"Retriever error: {str(e)}")
                return "I'm having trouble accessing the knowledge base. Please try again.", ""

            if not relevant_docs:
                return self._handle_no_relevant_docs(question)

            filtered_docs = self._filter_relevant_documents(relevant_docs, question)
            if not filtered_docs:
                return self._handle_no_relevant_docs(question)

            context = self._build_structured_context(filtered_docs)
            if len(context) > 20000:
                context = context[:20000] + "...[truncated]"

            if len(context) < 100:
                return (
                    "I found some related information, but it's not detailed enough "
                    "to provide a comprehensive answer. Please try rephrasing your "
                    "question or ask about a more specific topic.",
                    ""
                )

            # Generate prompt
            enhanced_prompt = get_rag_prompt(context, question)

            # Get LLM response
            answer = self.llm(enhanced_prompt)
            cleaned_answer = self._parse_and_format_response(answer)

            # Determine if sources should be shown
            should_show_sources = self._should_show_sources(
                cleaned_answer, context, filtered_docs, question
            )
            sources_info = (
                self._format_sources(filtered_docs) if should_show_sources else ""
            )

            return cleaned_answer, sources_info

        except Exception as e:
            logging.error(f"Error processing question: {str(e)}")
            import traceback
            traceback.print_exc()
            return "I encountered an error processing your question. Please try again.", ""

    def _query_streaming(self, question: str) -> Generator:
        """Streaming query - yields dict with 'content' and 'sources' keys."""
        try:
            if not question or not question.strip():
                yield {"content": "Please ask a question about the university.", "sources": "", "done": True}
                return

            if len(question) > 1000:
                yield {"content": "Please keep your questions under 1000 characters.", "sources": "", "done": True}
                return

            q_lower = question.lower()

            # Handle date/time queries
            if any(phrase in q_lower for phrase in [
                "what is the date", "what's the date", "current date",
                "today's date", "what date is it"
            ]):
                current_date = datetime.now().strftime("%A, %B %d, %Y")
                yield {"content": f"Today's date is {current_date}.", "sources": "", "done": True}
                return

            if any(phrase in q_lower for phrase in [
                "what time", "current time", "what's the time"
            ]):
                current_time = datetime.now().strftime("%I:%M %p")
                yield {"content": f"The current time is {current_time}.", "sources": "", "done": True}
                return

            # Handle greetings
            is_greeting = (
                    any(g in q_lower for g in GREETING_KEYWORDS)
                    and len(question.split()) <= 3
            )
            if is_greeting:
                yield {"content": random.choice(GREETING_RESPONSES), "sources": "", "done": True}
                return

            # Retrieve relevant documents
            try:
                relevant_docs = self.retriever.get_relevant_documents(question)
            except Exception as e:
                logging.error(f"Retriever error: {str(e)}")
                yield {"content": "I'm having trouble accessing the knowledge base. Please try again.", "sources": "",
                       "done": True}
                return

            if not relevant_docs:
                result = self._handle_no_relevant_docs(question)
                yield {"content": result[0], "sources": result[1], "done": True}
                return

            filtered_docs = self._filter_relevant_documents(relevant_docs, question)
            if not filtered_docs:
                result = self._handle_no_relevant_docs(question)
                yield {"content": result[0], "sources": result[1], "done": True}
                return

            context = self._build_structured_context(filtered_docs)
            if len(context) > 20000:
                context = context[:20000] + "...[truncated]"

            if len(context) < 100:
                yield {
                    "content": (
                        "I found some related information, but it's not detailed enough "
                        "to provide a comprehensive answer. Please try rephrasing your "
                        "question or ask about a more specific topic."
                    ),
                    "sources": "",
                    "done": True
                }
                return

            # Generate prompt
            enhanced_prompt = get_rag_prompt(context, question)

            # Stream the response
            accumulated_answer = ""
            for chunk in self.llm.stream(enhanced_prompt):
                accumulated_answer += chunk
                # Parse as we go to show formatted content
                parsed_chunk = self._parse_and_format_response(accumulated_answer)
                yield {"content": parsed_chunk, "sources": "", "done": False}

            # Final cleanup and sources
            final_answer = self._parse_and_format_response(accumulated_answer)
            should_show_sources = self._should_show_sources(
                final_answer, context, filtered_docs, question
            )
            sources_info = (
                self._format_sources(filtered_docs) if should_show_sources else ""
            )

            yield {"content": final_answer, "sources": sources_info, "done": True}

        except Exception as e:
            logging.error(f"Error in streaming query: {str(e)}")
            import traceback
            traceback.print_exc()
            yield {"content": "I encountered an error processing your question. Please try again.", "sources": "",
                   "done": True}