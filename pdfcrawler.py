import os
import json
import hashlib
import logging
import requests
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from pymongo import MongoClient
import PyPDF2
from io import BytesIO

# Import your config
from configfile import  CONFIG, website_url, PDF_URLS
mongo_config = CONFIG['mongodb']

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class PDFContent:
    """Data class to structure PDF content"""
    url: str
    file_name: str
    file_hash: str
    total_pages: int
    file_size_bytes: int

    # Content fields
    text_content: str
    pages_content: List[Dict]  # List of {page_num, text, metadata}

    # Metadata fields
    pdf_metadata: Dict  # Author, Title, Subject, Creator, etc.

    # Processing info
    extraction_method: str  # 'text', 'ocr', 'hybrid'
    processed_at: str
    content_hash: str
    status_code: int

    # Classification
    category: str = ""
    section: str = ""
    keywords: List[str] = None

    # Error tracking
    errors: List[str] = None


class MongoDBManager:
    """MongoDB connection manager"""

    def __init__(self, config: Dict):
        self.config = config
        self.client = None
        self.db = None

    def connect(self):
        """Get MongoDB database connection"""
        if not self.client:
            self.client = MongoClient(self.config["host"])
            self.db = self.client[self.config["database"]]
        return self.db

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            self.client = None


class PDFURLCrawler:
    """Download and extract PDF content from URLs - Similar to web crawler"""

    def __init__(self, mongo_config: Dict, target_sections: List[str] = None, config: Dict = None):
        self.mongo_config = mongo_config
        self.db_manager = MongoDBManager(mongo_config)
        self.db = self.db_manager.connect()

        # Target sections for categorization
        self.target_sections = target_sections or []

        # Crawler config (similar to web crawler)
        self.config = {
            'timeout': 30,
            'delay': 0.5,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'max_retries': 3,
            'incremental_mode': True
        }
        if config:
            self.config.update(config)

        # Session for downloads
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config['user_agent']
        })

        # State tracking (like web crawler)
        self.visited_urls = set()
        self.failed_urls = set()
        self.skipped_urls = set()
        self.updated_urls = set()

        # Initialize database
        self._init_database()

        # Load processing history
        self.processing_history = self._load_processing_history()

    def _init_database(self):
        """Ensure MongoDB indexes for pdf_content collection"""
        try:
            collection = self.db["pdf_content"]
            collection.create_index("url", unique=True)
            collection.create_index("file_hash")
            collection.create_index("processed_at")
            collection.create_index("category")
            collection.create_index("section")
            collection.create_index("content_hash")
            logger.info("MongoDB pdf_content indexes created successfully")
        except Exception as e:
            logger.error(f"Error initializing MongoDB: {e}")
            raise

    def _load_processing_history(self) -> Dict[str, Dict]:
        """Load previous processing history from MongoDB"""
        history = {}
        try:
            collection = self.db["pdf_content"]
            for doc in collection.find({}, {"url": 1, "file_hash": 1, "content_hash": 1, "processed_at": 1}):
                history[doc["url"]] = {
                    "file_hash": doc.get("file_hash", ""),
                    "content_hash": doc.get("content_hash", ""),
                    "processed_at": doc.get("processed_at", "")
                }
            logger.info(f"Loaded {len(history)} PDFs from processing history")
        except Exception as e:
            logger.error(f"Error loading processing history: {e}")
        return history

    def _generate_content_hash(self, content: str) -> str:
        """Generate hash of extracted content"""
        if not content:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _should_process_url(self, url: str) -> tuple:
        """Check if PDF URL needs to be processed (similar to web crawler logic)"""
        if not self.config['incremental_mode']:
            return True, "incremental_mode_disabled"

        if url not in self.processing_history:
            return True, "new_url"

        # Check if forced recrawl time has passed
        try:
            record = self.processing_history[url]
            last_processed = record.get("processed_at", "")
            if last_processed:
                if isinstance(last_processed, datetime):
                    last_processed_dt = last_processed
                else:
                    last_processed_dt = datetime.fromisoformat(last_processed)

                days_since = (datetime.now() - last_processed_dt).days
                if days_since >= 30:  # Recrawl after 30 days
                    return True, f"force_recrawl_after_{days_since}_days"
        except Exception:
            return True, "invalid_last_processed_date"

        return False, "recently_processed"

    def _categorize_pdf(self, url: str, text_content: str) -> tuple:
        """Categorize PDF by section based on URL and content"""
        url_lower = url.lower()
        text_lower = text_content[:1000].lower()  # Check first 1000 chars

        for section in self.target_sections:
            if section.lower() in url_lower or section.lower() in text_lower:
                return "document", section

        return "document", "uncategorized"

    def _extract_pdf_metadata(self, pdf_reader) -> Dict:
        """Extract PDF metadata"""
        try:
            metadata = pdf_reader.metadata
            return {
                "title": metadata.get("/Title", "") if metadata else "",
                "author": metadata.get("/Author", "") if metadata else "",
                "subject": metadata.get("/Subject", "") if metadata else "",
                "creator": metadata.get("/Creator", "") if metadata else "",
                "producer": metadata.get("/Producer", "") if metadata else "",
                "creation_date": str(metadata.get("/CreationDate", "")) if metadata else "",
                "modification_date": str(metadata.get("/ModDate", "")) if metadata else ""
            }
        except Exception as e:
            logger.warning(f"Error extracting metadata: {e}")
            return {}

    def _extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> tuple:
        """Extract text from PDF bytes"""
        try:
            pdf_file = BytesIO(pdf_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            total_pages = len(pdf_reader.pages)

            # Extract metadata
            pdf_metadata = self._extract_pdf_metadata(pdf_reader)

            # Extract text from each page
            pages_content = []
            full_text = []

            for page_num in range(total_pages):
                try:
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()

                    pages_content.append({
                        "page_number": page_num + 1,
                        "text": page_text,
                        "char_count": len(page_text)
                    })

                    full_text.append(page_text)
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num + 1}: {e}")
                    pages_content.append({
                        "page_number": page_num + 1,
                        "text": "",
                        "error": str(e)
                    })

            combined_text = "\n\n".join(full_text)

            return combined_text, pages_content, pdf_metadata, total_pages, "text"

        except Exception as e:
            logger.error(f"Error reading PDF bytes: {e}")
            return "", [], {}, 0, "error"

    def download_and_extract_pdf(self, url: str) -> Optional[PDFContent]:
        """Download PDF from URL and extract content (similar to _crawl_single_page)"""
        try:
            file_name = os.path.basename(url).split('?')[0]  # Remove query params

            logger.info(f"Downloading: {url}")

            # Download PDF with retries
            response = None
            for attempt in range(self.config['max_retries']):
                try:
                    response = self.session.get(url, timeout=self.config['timeout'], stream=True)
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == self.config['max_retries'] - 1:
                        raise e
                    logger.warning(f"Retry {attempt + 1}/{self.config['max_retries']} for {url}")
                    import time
                    time.sleep(2)

            if response is None or response.status_code != 200:
                logger.warning(f'HTTP {response.status_code if response else "None"} for {url}')
                self.failed_urls.add(url)
                return None

            # Get PDF bytes
            pdf_bytes = response.content
            file_size = len(pdf_bytes)
            file_hash = hashlib.md5(pdf_bytes).hexdigest()

            # Extract text from PDF
            text_content, pages_content, pdf_metadata, total_pages, method = self._extract_text_from_pdf_bytes(
                pdf_bytes)

            # Check if content changed (incremental logic)
            if url in self.processing_history:
                old_hash = self.processing_history[url].get("content_hash", "")
                content_hash = self._generate_content_hash(text_content)

                if old_hash == content_hash:
                    logger.info(f"Content unchanged for {url}")
                    self.skipped_urls.add(url)
                    return None

            # Categorize PDF
            category, section = self._categorize_pdf(url, text_content)

            # Generate content hash
            content_hash = self._generate_content_hash(text_content)

            # Extract simple keywords
            words = set(word.lower() for word in text_content.split() if len(word) > 4)
            keywords = list(words)[:20]

            # Mark as updated
            self.updated_urls.add(url)

            # Create PDFContent object
            pdf_content = PDFContent(
                url=url,
                file_name=file_name,
                file_hash=file_hash,
                total_pages=total_pages,
                file_size_bytes=file_size,
                text_content=text_content,
                pages_content=pages_content,
                pdf_metadata=pdf_metadata,
                extraction_method=method,
                processed_at=datetime.now().isoformat(),
                content_hash=content_hash,
                status_code=response.status_code,
                category=category,
                section=section,
                keywords=keywords,
                errors=[]
            )

            return pdf_content

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            self.failed_urls.add(url)
            return None

    def save_pdf_content_to_database(self, pdf_content: PDFContent) -> bool:
        """Save PDF content to MongoDB"""
        try:
            collection = self.db["pdf_content"]
            doc = asdict(pdf_content)

            # Convert processed_at to datetime
            try:
                doc["processed_at"] = datetime.fromisoformat(pdf_content.processed_at)
            except:
                doc["processed_at"] = datetime.now()

            # Upsert by URL
            collection.update_one(
                {"url": pdf_content.url},
                {"$set": doc, "$setOnInsert": {"created_at": datetime.now()}},
                upsert=True
            )

            logger.info(f" Saved to MongoDB: {pdf_content.file_name}")
            return True

        except Exception as e:
            logger.error(f"Error saving to MongoDB: {e}")
            return False

    def load_urls_from_json(self, json_file_path: str) -> List[str]:
        """Load PDF URLs from JSON file (similar to web crawler's load_all_urls_from_json)"""
        logger.info(f" Loading PDF URLs from: {json_file_path}")

        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Get PDF URLs
            pdf_urls = data.get('pdf_urls', []) or data.get('urls', [])

            # Filter only PDF URLs
            pdf_urls = [url for url in pdf_urls if url.lower().endswith('.pdf')]

            logger.info(f"📄 Found {len(pdf_urls)} PDF URLs")
            return pdf_urls

        except FileNotFoundError:
            logger.error(f" File not found: {json_file_path}")
            return []
        except Exception as e:
            logger.error(f" Error loading URLs: {e}")
            return []

    def crawl_pdf_urls(self, pdf_urls: List[str], max_pdfs: int = None) -> Dict:
        """Crawl PDF URLs (similar to crawl_website method)"""
        logger.info("=" * 70)
        logger.info(" STARTING PDF URL CRAWLING")
        logger.info("=" * 70)
        logger.info(f"Total PDF URLs: {len(pdf_urls)}")
        logger.info(f"Incremental mode: {self.config['incremental_mode']}")
        logger.info(f"MongoDB: {self.mongo_config['host']} / {self.mongo_config['database']}")
        logger.info("=" * 70)

        processed_count = 0

        for url in pdf_urls:
            if max_pdfs and processed_count >= max_pdfs:
                logger.info(f"Reached max PDF limit: {max_pdfs}")
                break

            # Skip if already visited in this session
            if url in self.visited_urls:
                continue

            self.visited_urls.add(url)

            # Check if should process
            should_process, reason = self._should_process_url(url)

            if not should_process:
                logger.info(f"  Skipping {url}: {reason}")
                self.skipped_urls.add(url)
                continue

            logger.info(f" Processing ({processed_count + 1}/{len(pdf_urls)}): {reason}")

            # Download and extract
            pdf_content = self.download_and_extract_pdf(url)

            if pdf_content:
                # Save to MongoDB
                if self.save_pdf_content_to_database(pdf_content):
                    processed_count += 1

                    # Update history
                    self.processing_history[url] = {
                        "file_hash": pdf_content.file_hash,
                        "content_hash": pdf_content.content_hash,
                        "processed_at": pdf_content.processed_at
                    }

            # Delay between requests
            import time
            time.sleep(self.config['delay'])

        return {
            "total_urls": len(pdf_urls),
            "processed": processed_count,
            "updated": len(self.updated_urls),
            "skipped": len(self.skipped_urls),
            "failed": len(self.failed_urls)
        }

    def get_statistics(self) -> Dict:
        """Get PDF processing statistics from MongoDB"""
        try:
            collection = self.db["pdf_content"]

            stats = {}
            stats["total_pdfs"] = collection.count_documents({})

            # PDFs by section
            pipeline = [
                {"$group": {"_id": "$section", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}}
            ]
            stats["pdfs_by_section"] = {
                item["_id"]: item["count"] for item in collection.aggregate(pipeline)
            }

            # PDFs by extraction method
            pipeline = [{"$group": {"_id": "$extraction_method", "count": {"$sum": 1}}}]
            stats["pdfs_by_method"] = {
                item["_id"]: item["count"] for item in collection.aggregate(pipeline)
            }

            # Average pages
            pipeline = [
                {"$group": {"_id": None, "avg_pages": {"$avg": "$total_pages"}}}
            ]
            agg = list(collection.aggregate(pipeline))
            stats["average_pages_per_pdf"] = round(agg[0]["avg_pages"], 2) if agg else 0

            # Recent PDFs (last 7 days)
            since = datetime.now() - timedelta(days=7)
            stats["pdfs_last_7_days"] = collection.count_documents({"processed_at": {"$gte": since}})

            return stats

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}

    def close(self):
        """Close database connection"""
        self.db_manager.close()


# Main function
def crawl_pdfs_from_json(json_file_path: str, mongo_config: Dict,
                         target_sections: List[str] = None,
                         max_pdfs: int = None):
    """
    Crawl PDF URLs from JSON file and store content in MongoDB

    Args:
        json_file_path: Path to JSON file with PDF URLs
        mongo_config: MongoDB configuration
        target_sections: List of keywords for categorization
        max_pdfs: Optional limit on number of PDFs to process
    """

    # Initialize crawler
    crawler = PDFURLCrawler(mongo_config, target_sections)

    # Load URLs from JSON
    pdf_urls = crawler.load_urls_from_json(json_file_path)

    if not pdf_urls:
        logger.error("No PDF URLs found to process")
        return {}, {}

    # Crawl PDFs
    results = crawler.crawl_pdf_urls(pdf_urls, max_pdfs)

    # Get statistics
    stats = crawler.get_statistics()

    # Print results
    logger.info("\n" + "=" * 70)
    logger.info(" PDF CRAWLING COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Total PDF URLs: {results['total_urls']}")
    logger.info(f"PDFs processed: {results['processed']}")
    logger.info(f"PDFs updated: {results['updated']}")
    logger.info(f"PDFs skipped: {results['skipped']}")
    logger.info(f"Failed: {results['failed']}")
    logger.info("\n" + "=" * 70)
    logger.info(" DATABASE STATISTICS")
    logger.info("=" * 70)
    logger.info(f"Total PDFs in database: {stats.get('total_pdfs', 0)}")
    logger.info(f"Average pages per PDF: {stats.get('average_pages_per_pdf', 0)}")
    logger.info(f"PDFs processed (last 7 days): {stats.get('pdfs_last_7_days', 0)}")

    if stats.get('pdfs_by_section'):
        logger.info("\n PDFs by Section:")
        for section, count in sorted(stats['pdfs_by_section'].items()):
            logger.info(f"  {section}: {count}")

    logger.info("=" * 70)

    # Close connection
    crawler.close()

    return results, stats

def get_default_json_file():
    # list all JSON files in the directory
    json_files = list(PDF_URLS.glob("www_srmist_edu_in_PDF_ONLY_*.json"))
    print(json_files)

    if not json_files:
        raise FileNotFoundError("No JSON file found inside target_sections_urls directory")

    if len(json_files) > 1:
        print("Multiple JSON files found, using the first one automatically")

    return json_files[0]

if __name__ == "__main__":
    # MongoDB configuration
    MONGO_CONFIG = mongo_config

    # Target sections for categorization
    TARGET_SECTIONS = [
        'admission', 'admissions',
        'hostel', 'hostels',
        'placement', 'placements',
        'event', 'events',
        'alumni',
        'examination', 'examinations',
        'academic', 'academics',
        'research',
        'faculty',
        'student',
        'campus',
        'scholarship', 'scholarships',
        'curriculum',
        'syllabus'
    ]

    json_file = get_default_json_file()
    print(f"Using JSON file: {json_file}")
    # JSON file with PDF URLs
    # json_file = input("Enter JSON file path with PDF URLs: ").strip()
    # if not json_file:
    #     json_file = r'D:\ChatBot-University\Py\SRMISTCHATBOT\optimized_crawl\json_results\www_srmist_edu_in_PDF_ONLY_20251201_133431.json'

    # Process PDFs
    results, stats = crawl_pdfs_from_json(
        json_file_path=json_file,
        mongo_config=MONGO_CONFIG,
        target_sections= TARGET_SECTIONS,
        max_pdfs=None  # Process all PDFs
    )

    print("\n PDF URL crawling complete!")
    print(f"   Content stored in MongoDB collection: pdf_content")
    print(f"   Ready for embedding generation in separate pipeline")