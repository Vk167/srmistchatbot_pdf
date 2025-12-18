import os
from pathlib import Path

# Base project directory (assumes configfile.py is in the root)
BASE_DIR = Path(__file__).parent.absolute()


# Data directories
DATA_DIR = BASE_DIR / "data"

EMBEDDINGS_DIR = DATA_DIR / "embeddings"

PDF_URLS = BASE_DIR / "pdf_urls" / "json_results"

# File paths for common files
#embedding data
EMBEDDINGS_FILE = EMBEDDINGS_DIR

# Configuration settings
CONFIG = {

    "scraping": {
        "delay": 1.5,                  # seconds between requests
        "timeout": 30,                 # request timeout
        "max_retries": 6,
        "max_pages": 5000,
        "max_depth": 5,
        "max_workers": 3,
        "respect_robots_txt": True,
        "follow_external_links": False,
        "exclude_extensions": {
            ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
            ".css", ".js", ".zip", ".rar", ".exe", ".mp3", ".mp4", ".avi"
        },
        "exclude_patterns": [
            "/admin/", "/login/", "/logout/", "/register/", "/cart/", "/checkout/", 'void(0)', 'javascript:'
        ],
        "include_patterns": [""],      # allow override if you only want certain paths
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        ),

        # Incremental crawling extras
        "force_recrawl_days": 7,        # recrawl after N days (0 = only if changed)
        "check_modified_headers": True, # check Last-Modified + ETag
        "incremental_mode": True,       # skip unchanged pages
        "backup_old_data": True         # keep old crawl results
    },

    # Preprocessing settings
    "preprocessing": {
        "chunk_size": 500,
        "chunk_overlap": 50,
    },

    # Embedding settings
    "embedding": {
        "model_name": "all-MiniLM-L6-v2",
        'device': 'cpu',
        'normalize_embeddings': True,

    },


    # RAG Chatbot settings
    "ragchatbot": {
        "top_k": 10,  # number of relevant documents to retrieve
        "model_name":'models/gemini-2.5-flash'
    },

    # MONGODB Config
    "mongodb":{
        'host': 'localhost',
        # 'host': 'mongodb+srv://user:user@cluster0.z5cbckx.mongodb.net/',
        'port': 27017,
        'database': 'srmistpdfdb',
        # 'database': 'abc'
    }
}

website_url = "https://www.srmist.edu.in/"
