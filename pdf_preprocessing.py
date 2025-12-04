import json
import re
from typing import List, Dict, Any
from dataclasses import dataclass
import nltk
from nltk.tokenize import sent_tokenize
import os
from pymongo import MongoClient, ASCENDING
from datetime import datetime, timedelta

from configfile import CONFIG

# Configuration
preprocessing_config = CONFIG["preprocessing"]
mongodb = CONFIG['mongodb']


@dataclass
class TextChunk:
    """Structured text chunk for RAG"""
    chunk_id: str
    content: str
    source_url: str
    title: str
    chunk_type: str
    metadata: Dict[str, Any]
    word_count: int


class PDFTextPreprocessor:
    """Preprocess PDF content for RAG"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def clean_text(self, text: str):
        """Clean and normalize text"""
        if not text:
            return ""

        # Remove extra space and normalize
        text = re.sub(r"\s+", " ", text.strip())

        # Remove special characters but keep important punctuation
        text = re.sub(r"[^a-zA-Z0-9\s\.\!\?\,\:\;\-\(\)\|\n]", '', text)

        # Remove very short lines
        lines = text.split("\n")
        lines = [line.strip() for line in lines if len(line.strip()) > 15]
        text = '\n'.join(lines)

        return text

    def extract_university_keywords(self, text: str):
        """Extract university keywords"""
        keywords = {
            'programs': [],
            'departments': [],
            'courses': [],
            'requirements': [],
            'contact_info': []
        }

        if not text:
            return keywords

        text_lower = text.lower()

        # Extract programs/degrees
        program_patterns = [
            r'\b(?:bachelor|master|phd|doctorate|degree|program)\s+(?:of|in)\s+([^,\n\.]{3,30})',
            r'\b(computer science|engineering|business|medicine|law|arts|science)\b',
        ]

        for pattern in program_patterns:
            matches = re.findall(pattern, text_lower)
            keywords['programs'].extend([m.strip() for m in matches if m.strip()])

        # Extract departments
        dept_patterns = [
            r'\b(?:department of|school of|college of|faculty of)\s+([^,\n\.]{3,30})',
        ]

        for pattern in dept_patterns:
            matches = re.findall(pattern, text_lower)
            keywords['departments'].extend([m.strip() for m in matches if m.strip()])

        # Extract course codes
        course_pattern = r'\b[A-Z]{2,4}\s*\d{3,4}\b'
        keywords['courses'] = re.findall(course_pattern, text)

        # Extract requirements
        req_pattern = r'\b(?:prerequisite|requirement|required|mandatory)\s*:?\s*([^,\n\.]{5,50})'
        matches = re.findall(req_pattern, text_lower)
        keywords['requirements'] = [m.strip() for m in matches if m.strip()]

        # Extract contact info
        email_pattern = r'\b[\w\.-]+@[\w\.-]+\.\w+\b'
        phone_pattern = r'(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'

        keywords['contact_info'].extend(re.findall(email_pattern, text_lower))
        keywords['contact_info'].extend(re.findall(phone_pattern, text_lower))

        # Remove duplicates
        for key in keywords:
            keywords[key] = list(set([item for item in keywords[key] if item and len(item) > 2]))

        return keywords

    def chunk_text_smart(self, text: str):
        """Create smart chunks respecting sentence boundaries"""
        if not text or len(text.strip()) < 50:
            return []

        # Split into sentences
        try:
            sentences = sent_tokenize(text)
        except:
            sentences = text.split('. ')

        chunks = []
        current_chunk = ""
        current_word_count = 0

        for sentence in sentences:
            sentence_words = len(sentence.split())

            # If adding this sentence would exceed chunk size
            if current_word_count + sentence_words > self.chunk_size and current_chunk:
                chunks.append(current_chunk.strip())

                # Start new chunk with overlap
                if self.chunk_overlap > 0:
                    overlap_words = current_chunk.split()[-self.chunk_overlap:]
                    current_chunk = " ".join(overlap_words) + " " + sentence
                    current_word_count = len(overlap_words) + sentence_words
                else:
                    current_chunk = sentence
                    current_word_count = sentence_words
            else:
                current_chunk += " " + sentence if current_chunk else sentence
                current_word_count += sentence_words

        # Add the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def process_single_pdf(self, pdf_data):
        """Process a single PDF into universal structured RAG chunks"""
        chunks = []
        chunk_counter = 0

        def add_chunk(content, chunk_type, metadata=None):
            nonlocal chunk_counter, chunks
            if not content or len(content.strip()) < 5:
                return

            chunks.append(TextChunk(
                chunk_id=f"{pdf_data.url}#{chunk_type}_{chunk_counter}",
                content=content.strip(),
                source_url=pdf_data.url,
                title=pdf_data.file_name or "",
                chunk_type=chunk_type,
                metadata={
                    "chunk_id": f"{pdf_data.url}#{chunk_type}_{chunk_counter}",
                    "url": pdf_data.url,
                    "file_name": pdf_data.file_name,
                    "chunk_type": chunk_type,
                    "source_type": "pdf",
                    **(metadata or {})
                },
                word_count=len(content.split())
            ))
            chunk_counter += 1

        # PDF Metadata as a chunk (if available)
        if pdf_data.pdf_metadata:
            metadata_parts = []
            for key, value in pdf_data.pdf_metadata.items():
                if value:
                    metadata_parts.append(f"{key}: {value}")

            if metadata_parts:
                add_chunk(
                    " | ".join(metadata_parts),
                    "pdf_metadata",
                    {"pdf_metadata": pdf_data.pdf_metadata}
                )

        # Extract keywords from full text
        keywords = self.extract_university_keywords(pdf_data.text_content[:5000])

        # Process full text content with smart chunking
        if pdf_data.text_content:
            cleaned_text = self.clean_text(pdf_data.text_content)

            if cleaned_text:
                text_chunks = self.chunk_text_smart(cleaned_text)

                for chunk_text in text_chunks:
                    if len(chunk_text.split()) >= 10:
                        add_chunk(
                            chunk_text,
                            "pdf_content",
                            {
                                "total_pages": pdf_data.total_pages,
                                "file_size_bytes": pdf_data.file_size_bytes,
                                "section": pdf_data.section,
                                "category": pdf_data.category,
                                "university_keywords": keywords
                            }
                        )

        # Process individual pages (for page-specific retrieval)
        if pdf_data.pages_content:
            for page in pdf_data.pages_content:
                page_num = page.get('page_number', 0)
                page_text = page.get('text', '')

                if page_text and len(page_text.strip()) > 50:
                    cleaned_page = self.clean_text(page_text)

                    # Chunk each page if it's too long
                    if len(cleaned_page.split()) > self.chunk_size:
                        page_chunks = self.chunk_text_smart(cleaned_page)
                        for i, chunk in enumerate(page_chunks):
                            add_chunk(
                                chunk,
                                "pdf_page",
                                {
                                    "page_number": page_num,
                                    "page_chunk_index": i,
                                    "total_pages": pdf_data.total_pages,
                                    "section": pdf_data.section
                                }
                            )
                    else:
                        add_chunk(
                            cleaned_page,
                            "pdf_page",
                            {
                                "page_number": page_num,
                                "total_pages": pdf_data.total_pages,
                                "section": pdf_data.section
                            }
                        )

        return chunks


class DatabaseChunkManager:
    """Manage processed PDF chunks in MongoDB"""

    def __init__(self, mongo_uri: str = mongodb['host'], db_name: str = mongodb['database']):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.chunks = self.db["processed_pdf_chunks"]  # Different collection for PDF chunks
        self.sessions = self.db["pdf_processing_sessions"]

        # Create indexes
        self.chunks.create_index([("source_url", ASCENDING)])
        self.chunks.create_index([("chunk_type", ASCENDING)])
        self.chunks.create_index([("processed_at", ASCENDING)])
        self.chunks.create_index([("source_url", ASCENDING), ("chunk_type", ASCENDING)])
        self.chunks.create_index([("metadata.file_name", "text")])
        self.chunks.create_index([("metadata.section", ASCENDING)])
        self.chunks.create_index([("metadata.page_number", ASCENDING)])

        self.processed_urls = self._load_processed_urls()

    def _load_processed_urls(self) -> set:
        """Load already processed PDF URLs from MongoDB"""
        try:
            urls = {doc["source_url"] for doc in self.chunks.find({}, {"source_url": 1})}
            print(f"Found {len(urls)} already processed PDF URLs in MongoDB")
            return urls
        except Exception as e:
            print(f"Error loading processed URLs: {e}")
            return set()

    def should_process_pdf(self, pdf_data) -> bool:
        """Check if PDF needs processing"""
        url = getattr(pdf_data, "url", "")
        return url and url not in self.processed_urls

    def save_chunks_to_database(self, chunks: List[Any]) -> Dict[str, int]:
        """Insert or update processed chunks into MongoDB"""
        if not chunks:
            return {"created": 0, "updated": 0}

        created_count, updated_count = 0, 0

        try:
            for chunk in chunks:
                existing = self.chunks.find_one({"chunk_id": chunk.chunk_id})

                if existing:
                    self.chunks.update_one(
                        {"chunk_id": chunk.chunk_id},
                        {"$set": {
                            "content": chunk.content,
                            "title": chunk.title,
                            "chunk_type": chunk.chunk_type,
                            "metadata": chunk.metadata,
                            "word_count": chunk.word_count,
                            "processed_at": datetime.now(),
                            "updated_at": datetime.now()
                        }}
                    )
                    updated_count += 1
                else:
                    self.chunks.insert_one({
                        "chunk_id": chunk.chunk_id,
                        "content": chunk.content,
                        "source_url": chunk.source_url,
                        "title": chunk.title,
                        "chunk_type": chunk.chunk_type,
                        "metadata": chunk.metadata,
                        "word_count": chunk.word_count,
                        "processed_at": datetime.now(),
                        "created_at": datetime.now(),
                        "updated_at": datetime.now()
                    })
                    created_count += 1

                self.processed_urls.add(chunk.source_url)

            print(f"MongoDB: {created_count} chunks created, {updated_count} chunks updated")
            return {"created": created_count, "updated": updated_count}

        except Exception as e:
            print(f"Error saving chunks to MongoDB: {e}")
            return {"created": 0, "updated": 0}

    def save_processing_session(self, session_data: Dict):
        """Save processing session into MongoDB"""
        try:
            self.sessions.insert_one({
                "session_id": session_data["session_id"],
                "start_time": session_data["start_time"],
                "end_time": session_data["end_time"],
                "pdfs_processed": session_data["pdfs_processed"],
                "pdfs_skipped": session_data["pdfs_skipped"],
                "chunks_created": session_data["chunks_created"],
                "chunks_updated": session_data["chunks_updated"],
                "total_chunks": session_data["total_chunks"],
                "saved_at": datetime.utcnow()
            })
        except Exception as e:
            print(f"Error saving session: {e}")

    def get_chunk_statistics(self) -> Dict[str, Any]:
        """Aggregate statistics from MongoDB chunks collection"""
        try:
            total_chunks = self.chunks.count_documents({})
            unique_sources = len(self.chunks.distinct("source_url"))

            # Chunks by type
            pipeline = [
                {"$group": {"_id": "$chunk_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            chunk_types = {doc["_id"]: doc["count"] for doc in self.chunks.aggregate(pipeline)}

            # Chunks by section
            pipeline = [
                {"$group": {"_id": "$metadata.section", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            chunks_by_section = {doc["_id"]: doc["count"] for doc in self.chunks.aggregate(pipeline)}

            # Word count stats
            pipeline = [
                {"$match": {"word_count": {"$gt": 0}}},
                {"$group": {
                    "_id": None,
                    "avg": {"$avg": "$word_count"},
                    "min": {"$min": "$word_count"},
                    "max": {"$max": "$word_count"},
                }}
            ]
            wc_stats = list(self.chunks.aggregate(pipeline))
            avg_words, min_words, max_words = (0, 0, 0)
            if wc_stats:
                avg_words = round(wc_stats[0]["avg"], 1)
                min_words = wc_stats[0]["min"]
                max_words = wc_stats[0]["max"]

            # Recent activity (last 7 days)
            cutoff = datetime.utcnow() - timedelta(days=7)
            recent_chunks = self.chunks.count_documents({"processed_at": {"$gte": cutoff}})

            return {
                "total_chunks": total_chunks,
                "chunk_types": chunk_types,
                "chunks_by_section": chunks_by_section,
                "unique_source_pdfs": unique_sources,
                "average_words_per_chunk": avg_words,
                "min_words": min_words,
                "max_words": max_words,
                "chunks_last_7_days": recent_chunks
            }

        except Exception as e:
            print(f"Error getting chunk statistics from MongoDB: {e}")
            return {}


if __name__ == "__main__":
    print("=== PDF Database-Based Incremental Preprocessing (MongoDB) ===")

    # Initialize database chunk manager
    chunk_manager = DatabaseChunkManager()

    # Session tracking
    session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    start_time = datetime.now()

    all_new_chunks = []
    processed_count = 0
    skipped_count = 0

    # Fetch PDF data directly from MongoDB (pdf_content collection)
    try:
        pdf_data = list(chunk_manager.db["pdf_content"].find({}, {
            "url": 1,
            "file_name": 1,
            "file_hash": 1,
            "total_pages": 1,
            "file_size_bytes": 1,
            "text_content": 1,
            "pages_content": 1,
            "pdf_metadata": 1,
            "section": 1,
            "category": 1,
            "keywords": 1
        }))

        # Convert None to safe defaults
        for item in pdf_data:
            item["file_name"] = item.get("file_name", "") or ""
            item["file_hash"] = item.get("file_hash", "") or ""
            item["total_pages"] = item.get("total_pages", 0) or 0
            item["file_size_bytes"] = item.get("file_size_bytes", 0) or 0
            item["text_content"] = item.get("text_content", "") or ""
            item["pages_content"] = item.get("pages_content", []) or []
            item["pdf_metadata"] = item.get("pdf_metadata", {}) or {}
            item["section"] = item.get("section", "uncategorized") or "uncategorized"
            item["category"] = item.get("category", "document") or "document"
            item["keywords"] = item.get("keywords", []) or []

        print(f"Fetched {len(pdf_data)} PDFs from MongoDB")

    except Exception as e:
        print(f"Error fetching PDF data: {e}")
        pdf_data = []

    # Initialize preprocessor
    preprocessor = PDFTextPreprocessor(
        chunk_size=preprocessing_config['chunk_size'],
        chunk_overlap=preprocessing_config['chunk_overlap']
    )

    # Process each PDF
    from types import SimpleNamespace

    for item in pdf_data:
        try:
            pdf = SimpleNamespace(**item)

            if chunk_manager.should_process_pdf(pdf):
                try:
                    pdf_chunks = preprocessor.process_single_pdf(pdf)
                    all_new_chunks.extend(pdf_chunks)
                    processed_count += 1

                    if processed_count % 10 == 0:
                        print(f"Processed {processed_count} new PDFs")
                except Exception as e:
                    print(f"Error processing {getattr(pdf, 'url', 'unknown')}: {e}")
            else:
                skipped_count += 1
        except Exception as e:
            print(f"Error creating PDF object: {e}")
            continue

    # Save chunks to MongoDB
    save_results = chunk_manager.save_chunks_to_database(all_new_chunks)
    end_time = datetime.now()

    # Save session information
    session_data = {
        "session_id": session_id,
        "start_time": start_time,
        "end_time": end_time,
        "pdfs_processed": processed_count,
        "pdfs_skipped": skipped_count,
        "chunks_created": save_results["created"],
        "chunks_updated": save_results["updated"],
        "total_chunks": len(all_new_chunks)
    }
    chunk_manager.save_processing_session(session_data)

    # Get and display statistics
    stats = chunk_manager.get_chunk_statistics()

    print(f"\n=== Processing Results ===")
    print(f"Session ID: {session_id}")
    print(f"New PDFs processed: {processed_count}")
    print(f"PDFs skipped: {skipped_count}")
    print(f"Chunks created: {save_results['created']}")
    print(f"Chunks updated: {save_results['updated']}")

    print(f"\n=== MongoDB Statistics ===")
    print(f"Total chunks in database: {stats.get('total_chunks', 0)}")
    print(f"Unique source PDFs: {stats.get('unique_source_pdfs', 0)}")
    print(f"Average words per chunk: {stats.get('average_words_per_chunk', 0)}")
    print(f"Chunk types: {stats.get('chunk_types', {})}")
    print(f"Chunks by section: {stats.get('chunks_by_section', {})}")
    print(f"Recent activity (7 days): {stats.get('chunks_last_7_days', 0)} chunks")

    print(f"\nSuccess! All PDF chunks stored in MongoDB.")
    print(f"Database: {chunk_manager.db.name}")
    print(f"Collection: processed_pdf_chunks")