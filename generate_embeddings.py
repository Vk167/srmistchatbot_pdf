import os
import json
import hashlib
import logging
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
import gc

from langchain.docstore.document import Document
from pymongo import MongoClient
import numpy as np

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


from configfile import EMBEDDINGS_FILE, CONFIG
embedding_config = CONFIG['embedding']
mongodb = CONFIG['mongodb']

output_dir = EMBEDDINGS_FILE


class IncrementalEmbeddingsManager:
    """Robust incremental embeddings system with proper error handling"""

    def __init__(self, mongo_config: Dict, embedding_config: Dict, output_dir: str, batch_size: int = 100):
        self.mongo_config = mongo_config
        self.embedding_config = embedding_config
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.embeddings_model = None
        self.mongo_client = None

        # Validate configurations
        self._validate_config()

        # Initialize components
        self._init_mongo_connection()
        self._init_embeddings_model()

    def _validate_config(self):
        """Validate configuration parameters"""
        required_mongo_keys = ['host', 'port', 'database']
        for key in required_mongo_keys:
            if key not in self.mongo_config:
                raise ValueError(f"Missing required MongoDB config: {key}")

        required_embedding_keys = ['model_name']
        for key in required_embedding_keys:
            if key not in self.embedding_config:
                raise ValueError(f"Missing required embedding config: {key}")

    def _init_mongo_connection(self):
        """Initialize MongoDB connection with error handling"""
        try:
            if self.mongo_config.get('username') and self.mongo_config.get('password'):
                connection_string = f"mongodb://{self.mongo_config['username']}:{self.mongo_config['password']}@{self.mongo_config['host']}:{self.mongo_config['port']}/{self.mongo_config.get('auth_source', 'admin')}"
            else:
                connection_string = f"mongodb://{self.mongo_config['host']}:{self.mongo_config['port']}"

            self.mongo_client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            # Test connection
            self.mongo_client.server_info()
            logger.info("MongoDB connection established successfully")

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def _init_embeddings_model(self):
        """Initialize embeddings model with error handling"""
        try:
            logger.info(f"Loading embedding model: {self.embedding_config['model_name']}")
            self.embeddings_model = HuggingFaceEmbeddings(
                model_name=self.embedding_config["model_name"],
                model_kwargs={"device": self.embedding_config.get("device", "cpu")},
                encode_kwargs={"normalize_embeddings": self.embedding_config.get("normalize_embeddings", True)}
            )
            logger.info("Embedding model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def _calculate_content_hash(self, content: str, metadata: Dict) -> str:
        """Calculate hash for content and metadata"""
        # Create stable metadata string (sorted keys for consistency)
        def default_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return str(obj)
        metadata_str = json.dumps(metadata, sort_keys=True, ensure_ascii=False, default = default_serializer)
        combined = f"{content}|{metadata_str}"
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    def load_chunks_from_mongo(self, limit: Optional[int] = None) -> List[Dict]:
        try:
            db = self.mongo_client[self.mongo_config['database']]
            # collection = db.processed_chunks #---For URLs and html pages DB
            collection = db.processed_pdf_chunks #---For Pdf page content DB

            # Optional filters from config
            query_filter: Dict = {}

            # e.g. only include important chunk types
            allowed_types = self.embedding_config.get("allowed_chunk_types")
            if allowed_types:
                query_filter["chunk_type"] = {"$in": allowed_types}

            # ignore tiny chunks
            min_words = self.embedding_config.get("min_word_count", 5)
            query_filter["word_count"] = {"$gte": min_words}

            query = collection.find(query_filter).sort('created_at', -1)
            if limit:
                query = query.limit(limit)

            chunks = list(query)
            logger.info(f"Loaded {len(chunks)} chunks from MongoDB")

            # Convert MongoDB ObjectIds to strings
            for chunk in chunks:
                if '_id' in chunk:
                    chunk['_id'] = str(chunk['_id'])

            return chunks

        except Exception as e:
            logger.error(f"Error loading chunks from MongoDB: {e}")
            raise

    def _load_existing_vector_store(self) -> Tuple[Optional[FAISS], Dict[str, str]]:
        """Load existing FAISS vector store and extract document hashes"""
        if not os.path.exists(self.output_dir):
            logger.info("No existing FAISS store found")
            return None, {}

        try:
            logger.info("Loading existing FAISS vector store...")
            vector_store = FAISS.load_local(
                self.output_dir,
                self.embeddings_model,
                allow_dangerous_deserialization=True
            )

            # Extract document hashes for comparison
            existing_hashes = {}
            if hasattr(vector_store.docstore, '_dict'):
                for doc_id, doc in vector_store.docstore._dict.items():
                    chunk_id = doc.metadata.get("chunk_id")
                    if chunk_id:
                        # Calculate hash for existing document
                        doc_hash = self._calculate_content_hash(doc.page_content, doc.metadata)
                        existing_hashes[chunk_id] = doc_hash

            logger.info(f"Loaded existing vector store with {len(existing_hashes)} documents")
            return vector_store, existing_hashes

        except Exception as e:
            logger.error(f"Failed to load existing FAISS store: {e}")
            return None, {}

    def _create_documents_batch(self, chunks_batch: List[Dict]) -> List[Document]:
        """Create LangChain Documents from a batch of chunks"""
        documents = []

        for chunk in chunks_batch:
            try:
                # Validate required fields
                # required_fields = ['chunk_id', 'content', 'source_url', 'title', 'chunk_type']
                # for field in required_fields:
                #     if field not in chunk:
                #         logger.warning(f"Chunk missing required field '{field}', skipping")
                #         continue
                required_fields = ['chunk_id', 'content', 'source_url', 'title', 'chunk_type']
                if not all(field in chunk for field in required_fields):
                    logger.warning(f"Chunk missing required fields, skipping: {chunk.get('chunk_id', 'no-id')}")
                    continue

                # Create metadata
                metadata = {
                    "chunk_id": chunk["chunk_id"],
                    "source": chunk["source_url"],
                    "url": chunk["source_url"],
                    "title": chunk["title"],
                    "chunk_type": chunk["chunk_type"],
                    "word_count": chunk.get("word_count", 0),
                    "processed_at": chunk.get("processed_at", ""),
                }

                # Add chunk-specific metadata
                if "metadata" in chunk and isinstance(chunk["metadata"], dict):
                    metadata.update(chunk["metadata"])

                # Create document
                doc = Document(page_content=chunk["content"], metadata=metadata)
                documents.append(doc)

            except Exception as e:
                logger.warning(f"Error processing chunk {chunk.get('chunk_id', 'unknown')}: {e}")
                continue

        return documents

    def _identify_changes(self, documents: List[Document], existing_hashes: Dict[str, str]) -> Tuple[
        List[Document], List[str]]:
        """Identify new and updated documents"""
        new_docs = []
        updated_chunk_ids = []

        for doc in documents:
            chunk_id = doc.metadata.get("chunk_id")
            if not chunk_id:
                logger.warning("Document missing chunk_id, treating as new")
                new_docs.append(doc)
                continue

            # Calculate current hash
            current_hash = self._calculate_content_hash(doc.page_content, doc.metadata)

            if chunk_id not in existing_hashes:
                # New document
                new_docs.append(doc)
            elif existing_hashes[chunk_id] != current_hash:
                # Updated document
                new_docs.append(doc)  # Will be added after removal
                updated_chunk_ids.append(chunk_id)
            # If hashes match, document is unchanged - skip

        return new_docs, updated_chunk_ids

    def _remove_documents_by_chunk_ids(self, vector_store: FAISS, chunk_ids_to_remove: List[str]) -> FAISS:
        """Safely remove documents from vector store by recreating it"""
        if not chunk_ids_to_remove:
            return vector_store

        try:
            logger.info(f"Removing {len(chunk_ids_to_remove)} updated documents")

            # Extract all documents except those to be removed
            remaining_docs = []
            if hasattr(vector_store.docstore, '_dict'):
                for doc_id, doc in vector_store.docstore._dict.items():
                    chunk_id = doc.metadata.get("chunk_id")
                    if chunk_id not in chunk_ids_to_remove:
                        remaining_docs.append(doc)

            # Create new vector store with remaining documents
            if remaining_docs:
                new_vector_store = FAISS.from_documents(remaining_docs, self.embeddings_model)
                logger.info(f"Recreated vector store with {len(remaining_docs)} remaining documents")
                return new_vector_store
            else:
                # No remaining documents, will create fresh store
                return None

        except Exception as e:
            logger.error(f"Error removing documents: {e}")
            # Return original store if removal fails
            return vector_store

    def _save_vector_store_safely(self, vector_store: FAISS) -> bool:
        """Save vector store with backup and rollback"""
        backup_dir = f"{self.output_dir}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        try:
            # Create backup of existing store
            if os.path.exists(self.output_dir):
                import shutil
                shutil.copytree(self.output_dir, backup_dir)
                logger.info(f"Created backup at {backup_dir}")

            # Save new store
            vector_store.save_local(self.output_dir)
            logger.info(f"Vector store saved successfully to {self.output_dir}")

            # Remove backup if save successful
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)

            return True

        except Exception as e:
            logger.error(f"Error saving vector store: {e}")

            # Restore from backup if available
            if os.path.exists(backup_dir):
                try:
                    if os.path.exists(self.output_dir):
                        shutil.rmtree(self.output_dir)
                    shutil.move(backup_dir, self.output_dir)
                    logger.info("Restored from backup due to save failure")
                except Exception as restore_error:
                    logger.error(f"Failed to restore backup: {restore_error}")

            return False

    def create_embeddings_incrementally(self, limit: Optional[int] = None) -> Optional[FAISS]:
        """Main method to create embeddings incrementally"""
        try:
            logger.info("Starting incremental embeddings creation")

            # Load chunks from MongoDB
            chunks_data = self.load_chunks_from_mongo(limit=limit)
            if not chunks_data:
                logger.warning("No chunks found in MongoDB")
                return None

            # Load existing vector store
            vector_store, existing_hashes = self._load_existing_vector_store()

            # Process chunks in batches to manage memory
            all_new_docs = []
            all_updated_chunk_ids = []

            for i in range(0, len(chunks_data), self.batch_size):
                batch = chunks_data[i:i + self.batch_size]
                logger.info(
                    f"Processing batch {i // self.batch_size + 1}/{(len(chunks_data) + self.batch_size - 1) // self.batch_size}")

                # Create documents for this batch
                documents_batch = self._create_documents_batch(batch)

                # Identify changes
                new_docs, updated_chunk_ids = self._identify_changes(documents_batch, existing_hashes)

                all_new_docs.extend(new_docs)
                all_updated_chunk_ids.extend(updated_chunk_ids)

                # Free memory
                del documents_batch
                gc.collect()

            logger.info(
                f"Found {len(all_new_docs)} new/updated documents, {len(all_updated_chunk_ids)} documents to remove")

            # Handle updates
            if vector_store is None:
                # First run - create new vector store
                if all_new_docs:
                    logger.info("Creating new FAISS vector store...")
                    vector_store = FAISS.from_documents(all_new_docs, self.embeddings_model)
                    if self._save_vector_store_safely(vector_store):
                        logger.info("Vector store created successfully")
                    return vector_store
                else:
                    logger.warning("No documents to create embeddings for")
                    return None

            # Update existing vector store
            changes_made = False

            # Remove updated documents
            if all_updated_chunk_ids:
                vector_store = self._remove_documents_by_chunk_ids(vector_store, all_updated_chunk_ids)
                changes_made = True

            # Add new/updated documents
            if all_new_docs:
                if vector_store is None:
                    # All documents were removed, create fresh store
                    vector_store = FAISS.from_documents(all_new_docs, self.embeddings_model)
                else:
                    # Add to existing store in batches
                    for i in range(0, len(all_new_docs), self.batch_size):
                        batch = all_new_docs[i:i + self.batch_size]
                        vector_store.add_documents(batch)
                        logger.info(f"Added batch {i // self.batch_size + 1} to vector store")

                changes_made = True

            # Save if changes were made
            if changes_made:
                if self._save_vector_store_safely(vector_store):
                    logger.info("Vector store updated successfully")
                return vector_store
            else:
                logger.info("No changes detected, vector store unchanged")
                return vector_store

        except Exception as e:
            logger.error(f"Error in incremental embeddings creation: {e}")
            raise

        finally:
            # Cleanup
            if self.mongo_client:
                self.mongo_client.close()

    def get_vector_store_stats(self) -> Dict:
        """Get statistics about the vector store"""
        try:
            if not os.path.exists(self.output_dir):
                return {"exists": False, "document_count": 0}

            vector_store = FAISS.load_local(
                self.output_dir,
                self.embeddings_model,
                allow_dangerous_deserialization=True
            )

            doc_count = len(vector_store.docstore._dict) if hasattr(vector_store.docstore, '_dict') else 0

            # Get chunk type distribution
            chunk_types = {}
            if hasattr(vector_store.docstore, '_dict'):
                for doc in vector_store.docstore._dict.values():
                    chunk_type = doc.metadata.get("chunk_type", "unknown")
                    chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1

            return {
                "exists": True,
                "document_count": doc_count,
                "chunk_type_distribution": chunk_types,
                "index_size": vector_store.index.ntotal if hasattr(vector_store, 'index') else 0
            }

        except Exception as e:
            logger.error(f"Error getting vector store stats: {e}")
            return {"exists": False, "error": str(e)}


def create_embeddings_with_langchain(mongo_config: Dict, embedding_config: Dict, output_dir: str,
                                     limit: Optional[int] = None, batch_size: int = 100):
    """
    Enhanced function to create embeddings using LangChain with proper error handling

    Args:
        mongo_config: MongoDB configuration dictionary
        embedding_config: Embedding model configuration
        output_dir: Directory to save FAISS vector store
        limit: Optional limit on number of chunks to process
        batch_size: Batch size for processing chunks

    Returns:
        FAISS vector store or None if failed
    """
    try:
        # Create embeddings manager
        embeddings_manager = IncrementalEmbeddingsManager(
            mongo_config=mongo_config,
            embedding_config=embedding_config,
            output_dir=output_dir,
            batch_size=batch_size
        )

        # Create embeddings incrementally
        vector_store = embeddings_manager.create_embeddings_incrementally(limit=limit)

        # Get and display statistics
        stats = embeddings_manager.get_vector_store_stats()
        logger.info(f"Vector store statistics: {stats}")

        return vector_store

    except Exception as e:
        logger.error(f"Failed to create embeddings: {e}")
        return None


# Example usage
if __name__ == "__main__":


    # Create embeddings
    vector_store = create_embeddings_with_langchain(
        mongo_config=mongodb,
        embedding_config=embedding_config,
        output_dir=output_dir,
        # batch_size=50  # Adjust based on your memory
    )

    if vector_store:
        print("Embeddings created successfully!")
        print(f"Vector store saved to: {output_dir}")
    else:
        print("Failed to create embeddings")