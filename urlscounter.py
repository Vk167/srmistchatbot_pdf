# import requests
# import time
# import json
# import os
# from bs4 import BeautifulSoup
# from urllib.parse import urljoin, urlparse, urlunparse
# from collections import deque, defaultdict
# from datetime import datetime
# from typing import Set, Dict, List, Tuple
# import logging
#
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(levelname)s - %(message)s"
# )
# logger = logging.getLogger(__name__)
#
#
# class FastURLCounter:
#     """Lightweight URL discovery and counter with specific subdomain control"""
#
#     def __init__(self, start_url: str, config: Dict = None):
#         self.start_url = start_url
#         parsed = urlparse(start_url)
#         self.domain = parsed.netloc
#         self.base_scheme = parsed.scheme
#
#         # Extract base domain for subdomain matching
#         domain_parts = self.domain.split('.')
#         if len(domain_parts) >= 2:
#             self.base_domain = '.'.join(domain_parts[-2:])
#         else:
#             self.base_domain = self.domain
#
#         # Default configuration
#         self.config = {
#             'max_depth': 6,
#             'timeout': 10,
#             'delay': 0.3,
#             'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
#             'exclude_extensions': [
#                 '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico',
#                 '.zip', '.mp4', '.mp3', '.avi', '.mov',
#                 '.css', '.js', '.woff', '.woff2', '.ttf', '.eot'
#             ],
#             'exclude_patterns': [
#                 '/wp-admin/', '/wp-content/uploads/',
#                 '/cdn-cgi/', '/assets/images/'
#             ],
#             'include_patterns': [],
#             'max_urls': None,
#             'use_head_requests': True,
#             'target_sections': [],
#             'allowed_subdomains': [],  # ONLY these subdomains will be crawled
#             'document_extensions': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
#         }
#
#         if config:
#             self.config.update(config)
#
#         # Normalize allowed subdomains to lowercase
#         self.allowed_subdomains = set(s.lower() for s in self.config['allowed_subdomains'])
#
#         # Session for connection pooling
#         self.session = requests.Session()
#         self.session.headers.update({
#             'User-Agent': self.config['user_agent'],
#         })
#
#         # State tracking
#         self.urls_to_visit = deque([(start_url, 0)])
#         self.visited_urls: Set[str] = set()
#         self.internal_urls: Set[str] = set()
#         self.external_urls: Set[str] = set()
#         self.failed_urls: Set[str] = set()
#         self.url_metadata: Dict[str, Dict] = {}
#         self.urls_by_depth: Dict[int, List[str]] = {}
#
#         # Document tracking
#         self.document_urls: Set[str] = set()
#         self.documents_by_type: Dict[str, List[str]] = defaultdict(list)
#         self.documents_by_section: Dict[str, List[str]] = defaultdict(list)
#         self.uncategorized_documents: List[str] = []
#         self.html_urls: Set[str] = set()
#
#         # Subdomain tracking
#         self.subdomains_found: Set[str] = set()
#         self.blocked_subdomains: Set[str] = set()  # Track rejected subdomains
#
#     def _normalize_url(self, url: str) -> str:
#         """Normalize URL for consistent comparison"""
#         try:
#             parsed = urlparse(url)
#             normalized = urlunparse((
#                 parsed.scheme,
#                 parsed.netloc.lower(),
#                 parsed.path.rstrip('/') if parsed.path != '/' else '/',
#                 parsed.params,
#                 parsed.query,
#                 ''
#             ))
#             return normalized
#         except:
#             return url
#
#     def _is_allowed_domain(self, url: str) -> bool:
#         """
#         Check if URL belongs to an allowed subdomain
#         CRITICAL: Only crawl URLs from explicitly allowed subdomains
#         """
#         try:
#             parsed = urlparse(url)
#             url_domain = parsed.netloc.lower()
#
#             # Check if this exact domain is in allowed list
#             is_allowed = url_domain in self.allowed_subdomains
#
#             if not is_allowed:
#                 # Track blocked subdomains for reporting
#                 if url_domain.endswith('.' + self.base_domain) or url_domain == self.base_domain:
#                     self.blocked_subdomains.add(url_domain)
#
#             return is_allowed
#         except:
#             return False
#
#     def _is_document_url(self, url: str, content_type: str = None) -> Tuple[bool, str]:
#         """Check if URL points to a document and return (is_document, extension)"""
#         url_lower = url.lower()
#
#         # Check file extension
#         for ext in self.config['document_extensions']:
#             if url_lower.endswith(ext):
#                 return (True, ext.lstrip('.'))
#
#         # Check content type if available
#         if content_type:
#             content_type_lower = content_type.lower()
#             doc_types = {
#                 'application/pdf': 'pdf',
#                 'application/vnd.ms-excel': 'xls',
#                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
#                 'application/msword': 'doc',
#                 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
#                 'application/vnd.ms-powerpoint': 'ppt',
#                 'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx'
#             }
#             for mime_type, ext in doc_types.items():
#                 if mime_type in content_type_lower:
#                     return (True, ext)
#
#         return (False, '')
#
#     def _categorize_document(self, url: str) -> str:
#         """Determine which section a document belongs to"""
#         url_lower = url.lower()
#
#         for section in self.config['target_sections']:
#             if section.lower() in url_lower:
#                 return section
#
#         return 'uncategorized'
#
#     def _is_valid_url(self, url: str, depth: int) -> bool:
#         """Check if URL should be processed"""
#         try:
#             parsed = urlparse(url)
#
#             # CRITICAL: Must be an allowed subdomain
#             if not self._is_allowed_domain(url):
#                 return False
#
#             # Check depth
#             if depth >= self.config['max_depth']:
#                 return False
#
#             # Check if it's a document - documents are always valid
#             is_doc, _ = self._is_document_url(url)
#
#             if not is_doc:
#                 # Check extensions for non-document files
#                 path = parsed.path.lower()
#                 if any(path.endswith(ext) for ext in self.config['exclude_extensions']):
#                     return False
#
#             # Check exclude patterns
#             if any(pattern in url for pattern in self.config['exclude_patterns']):
#                 return False
#
#             return True
#         except:
#             return False
#
#     def _extract_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
#         """Extract all links from page"""
#         links = []
#
#         for link_tag in soup.find_all('a', href=True):
#             href = link_tag['href'].strip()
#
#             if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
#                 continue
#
#             absolute_url = urljoin(current_url, href)
#             normalized = self._normalize_url(absolute_url)
#             links.append(normalized)
#
#         return links
#
#     def count_urls(self) -> Dict:
#         """Main counting method - discovers URLs from allowed subdomains only"""
#         logger.info(f"🚀 Starting crawl for: {self.start_url}")
#         logger.info(f"✅ ALLOWED subdomains: {', '.join(sorted(self.allowed_subdomains))}")
#         logger.info(f"Config: max_depth={self.config['max_depth']}, max_urls={self.config['max_urls']}")
#
#         if self.config['target_sections']:
#             logger.info(f"📄 Document categorization: {', '.join(self.config['target_sections'])}")
#
#         start_time = datetime.now()
#         processed = 0
#
#         while self.urls_to_visit:
#             if self.config['max_urls'] and processed >= self.config['max_urls']:
#                 logger.info(f"Reached max URL limit: {self.config['max_urls']}")
#                 break
#
#             current_url, depth = self.urls_to_visit.popleft()
#             current_url = self._normalize_url(current_url)
#
#             if current_url in self.visited_urls:
#                 continue
#
#             self.visited_urls.add(current_url)
#             self.internal_urls.add(current_url)
#             processed += 1
#
#             # Track subdomain
#             parsed = urlparse(current_url)
#             self.subdomains_found.add(parsed.netloc)
#
#             if depth not in self.urls_by_depth:
#                 self.urls_by_depth[depth] = []
#             self.urls_by_depth[depth].append(current_url)
#
#             if processed % 50 == 0:
#                 logger.info(
#                     f"Progress: {processed} URLs | Queue: {len(self.urls_to_visit)} | "
#                     f"Docs: {len(self.document_urls)} | Depth: {depth}"
#                 )
#
#             try:
#                 status_code = None
#                 content_type = None
#
#                 if self.config['use_head_requests']:
#                     try:
#                         response = self.session.head(
#                             current_url,
#                             timeout=self.config['timeout'],
#                             allow_redirects=True
#                         )
#                         status_code = response.status_code
#                         content_type = response.headers.get('Content-Type', '')
#                     except:
#                         pass
#
#                 if status_code is None:
#                     response = self.session.get(
#                         current_url,
#                         timeout=self.config['timeout']
#                     )
#                     status_code = response.status_code
#                     content_type = response.headers.get('Content-Type', '')
#
#                 # Check if it's a document
#                 is_document, doc_type = self._is_document_url(current_url, content_type)
#
#                 self.url_metadata[current_url] = {
#                     'status_code': status_code,
#                     'content_type': content_type,
#                     'depth': depth,
#                     'is_document': is_document,
#                     'document_type': doc_type if is_document else None
#                 }
#
#                 if status_code != 200:
#                     logger.debug(f"Status {status_code}: {current_url}")
#                     self.failed_urls.add(current_url)
#                     continue
#
#                 # Categorize documents
#                 if is_document:
#                     self.document_urls.add(current_url)
#                     self.documents_by_type[doc_type].append(current_url)
#
#                     section = self._categorize_document(current_url)
#
#                     if section == 'uncategorized':
#                         self.uncategorized_documents.append(current_url)
#                     else:
#                         self.documents_by_section[section].append(current_url)
#
#                     logger.debug(f"📄 {doc_type.upper()} found [{section}]: {current_url}")
#                     continue
#
#                 # Track HTML pages
#                 if 'text/html' in content_type.lower():
#                     self.html_urls.add(current_url)
#
#                 # Extract links only from HTML pages
#                 if 'text/html' in content_type.lower() and depth < self.config['max_depth'] - 1:
#                     if response.request.method == 'HEAD':
#                         response = self.session.get(
#                             current_url,
#                             timeout=self.config['timeout']
#                         )
#
#                     soup = BeautifulSoup(response.content, 'html.parser')
#                     links = self._extract_links(soup, current_url)
#
#                     for link in links:
#                         if self._is_allowed_domain(link):
#                             if (link not in self.visited_urls and
#                                     self._is_valid_url(link, depth + 1)):
#                                 self.urls_to_visit.append((link, depth + 1))
#                         else:
#                             self.external_urls.add(link)
#
#                 time.sleep(self.config['delay'])
#
#             except requests.exceptions.Timeout:
#                 logger.warning(f"Timeout: {current_url}")
#                 self.failed_urls.add(current_url)
#             except Exception as e:
#                 logger.warning(f"Error processing {current_url}: {str(e)[:100]}")
#                 self.failed_urls.add(current_url)
#
#         end_time = datetime.now()
#         duration = (end_time - start_time).total_seconds()
#
#         # Build results
#         results = {
#             'domain': self.domain,
#             'base_domain': self.base_domain,
#             'allowed_subdomains': sorted(list(self.allowed_subdomains)),
#             'subdomains_found': sorted(list(self.subdomains_found)),
#             'blocked_subdomains': sorted(list(self.blocked_subdomains)),
#             'start_url': self.start_url,
#             'timestamp': datetime.now().isoformat(),
#             'duration_seconds': round(duration, 2),
#             'urls_per_second': round(processed / duration, 2) if duration > 0 else 0,
#             'statistics': {
#                 'total_internal_urls': len(self.internal_urls),
#                 'total_external_urls': len(self.external_urls),
#                 'total_failed_urls': len(self.failed_urls),
#                 'total_discovered': len(self.internal_urls) + len(self.external_urls),
#                 'total_document_urls': len(self.document_urls),
#                 'total_html_urls': len(self.html_urls),
#                 'max_depth_reached': max(self.urls_by_depth.keys()) if self.urls_by_depth else 0,
#                 'urls_by_depth': {
#                     depth: len(urls) for depth, urls in self.urls_by_depth.items()
#                 },
#                 'documents_by_type': {
#                     doc_type: len(urls) for doc_type, urls in self.documents_by_type.items()
#                 },
#                 'documents_by_section': {
#                     section: len(urls) for section, urls in self.documents_by_section.items()
#                 },
#                 'uncategorized_documents': len(self.uncategorized_documents)
#             },
#             'urls': {
#                 'internal': sorted(list(self.internal_urls)),
#                 'external': sorted(list(self.external_urls)),
#                 'failed': sorted(list(self.failed_urls)),
#                 'documents_all': sorted(list(self.document_urls)),
#                 'html': sorted(list(self.html_urls))
#             },
#             'documents_by_type': {
#                 doc_type: sorted(urls) for doc_type, urls in self.documents_by_type.items()
#             },
#             'documents_by_section': {
#                 section: sorted(urls) for section, urls in self.documents_by_section.items()
#             },
#             'uncategorized_documents': sorted(self.uncategorized_documents),
#             'metadata': self.url_metadata
#         }
#
#         logger.info(f"✅ Discovery complete in {duration:.2f} seconds")
#         logger.info(f"📄 Found {len(self.document_urls)} documents")
#         if self.blocked_subdomains:
#             logger.info(
#                 f"🚫 Blocked {len(self.blocked_subdomains)} subdomains: {', '.join(sorted(list(self.blocked_subdomains))[:5])}")
#
#         return results
#
#     def save_results(self, results: Dict, output_dir: str = 'url_discovery', save_json_only: bool = False):
#         """Save results to files"""
#         os.makedirs(output_dir, exist_ok=True)
#
#         timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
#         domain_name = self.domain.replace('.', '_')
#
#         saved_files = {}
#
#         # Always save complete results as JSON
#         json_file = os.path.join(output_dir, f"{domain_name}_complete_{timestamp}.json")
#         with open(json_file, 'w', encoding='utf-8') as f:
#             json.dump(results, f, indent=2, ensure_ascii=False)
#         saved_files['complete_json'] = json_file
#
#         # Save separate JSON files
#         json_dir = os.path.join(output_dir, 'json_results')
#         os.makedirs(json_dir, exist_ok=True)
#
#         # HTML URLs JSON
#         html_json = os.path.join(json_dir, f"{domain_name}_html_pages_{timestamp}.json")
#         with open(html_json, 'w', encoding='utf-8') as f:
#             json.dump({
#                 'domain': self.domain,
#                 'timestamp': results['timestamp'],
#                 'total_count': len(results['urls']['html']),
#                 'urls': results['urls']['html']
#             }, f, indent=2, ensure_ascii=False)
#         saved_files['html_json'] = html_json
#
#         # All Documents JSON
#         all_docs_json = os.path.join(json_dir, f"{domain_name}_all_documents_{timestamp}.json")
#         with open(all_docs_json, 'w', encoding='utf-8') as f:
#             json.dump({
#                 'domain': self.domain,
#                 'timestamp': results['timestamp'],
#                 'total_count': len(results['urls']['documents_all']),
#                 'urls': results['urls']['documents_all']
#             }, f, indent=2, ensure_ascii=False)
#         saved_files['all_documents_json'] = all_docs_json
#
#         # Documents by type JSON
#         docs_by_type_json = os.path.join(json_dir, f"{domain_name}_documents_by_type_{timestamp}.json")
#         with open(docs_by_type_json, 'w', encoding='utf-8') as f:
#             json.dump({
#                 'domain': self.domain,
#                 'timestamp': results['timestamp'],
#                 'types': {
#                     doc_type: {
#                         'count': len(urls),
#                         'urls': urls
#                     } for doc_type, urls in results['documents_by_type'].items()
#                 }
#             }, f, indent=2, ensure_ascii=False)
#         saved_files['documents_by_type_json'] = docs_by_type_json
#
#         # Documents by section JSON
#         docs_by_section_json = os.path.join(json_dir, f"{domain_name}_documents_by_section_{timestamp}.json")
#         docs_section_data = {
#             'domain': self.domain,
#             'timestamp': results['timestamp'],
#             'sections': {}
#         }
#         for section, urls in results['documents_by_section'].items():
#             docs_section_data['sections'][section] = {
#                 'count': len(urls),
#                 'urls': urls
#             }
#         if results['uncategorized_documents']:
#             docs_section_data['sections']['uncategorized'] = {
#                 'count': len(results['uncategorized_documents']),
#                 'urls': results['uncategorized_documents']
#             }
#
#         with open(docs_by_section_json, 'w', encoding='utf-8') as f:
#             json.dump(docs_section_data, f, indent=2, ensure_ascii=False)
#         saved_files['documents_by_section_json'] = docs_by_section_json
#
#         # Statistics JSON
#         stats_json = os.path.join(json_dir, f"{domain_name}_statistics_{timestamp}.json")
#         with open(stats_json, 'w', encoding='utf-8') as f:
#             json.dump(results['statistics'], f, indent=2, ensure_ascii=False)
#         saved_files['statistics_json'] = stats_json
#
#         if save_json_only:
#             return saved_files
#
#         # Save text files for convenience
#         internal_file = os.path.join(output_dir, f"{domain_name}_internal_{timestamp}.txt")
#         with open(internal_file, 'w', encoding='utf-8') as f:
#             f.write(f"# Internal URLs for {self.domain}\n")
#             f.write(f"# Total: {results['statistics']['total_internal_urls']}\n")
#             f.write(f"# Generated: {results['timestamp']}\n\n")
#             for url in results['urls']['internal']:
#                 f.write(f"{url}\n")
#         saved_files['internal_urls'] = internal_file
#
#         # Additional text file saving code omitted for brevity...
#         # (Same as original code)
#
#         return saved_files
#
#     def print_summary(self, results: Dict):
#         """Print results summary to console"""
#         print("\n" + "=" * 70)
#         print("📊 URL DISCOVERY COMPLETE")
#         print("=" * 70)
#         print(f"Domain: {results['domain']}")
#         print(f"Allowed Subdomains: {', '.join(results['allowed_subdomains'])}")
#         print(f"Subdomains Crawled: {', '.join(results['subdomains_found'])}")
#         if results['blocked_subdomains']:
#             print(f"Blocked Subdomains: {', '.join(results['blocked_subdomains'][:5])}")
#         print(f"Duration: {results['duration_seconds']} seconds")
#         print(f"Speed: {results['urls_per_second']} URLs/second")
#         print("\n📈 STATISTICS:")
#         print(f"  Internal URLs: {results['statistics']['total_internal_urls']:,}")
#         print(f"  HTML Pages: {results['statistics']['total_html_urls']:,}")
#         print(f"  Document Files: {results['statistics']['total_document_urls']:,}")
#         print(f"  External URLs: {results['statistics']['total_external_urls']:,}")
#         print(f"  Failed URLs: {results['statistics']['total_failed_urls']:,}")
#
#         if results['statistics']['documents_by_type']:
#             print(f"\n📄 DOCUMENTS BY TYPE:")
#             for doc_type in sorted(results['statistics']['documents_by_type'].keys()):
#                 count = results['statistics']['documents_by_type'][doc_type]
#                 print(f"  {doc_type.upper()}: {count:,} files")
#
#         if results['statistics']['documents_by_section']:
#             print(f"\n📂 DOCUMENTS BY SECTION:")
#             for section in sorted(results['statistics']['documents_by_section'].keys()):
#                 count = results['statistics']['documents_by_section'][section]
#                 print(f"  {section}: {count:,} documents")
#         if results['statistics']['uncategorized_documents'] > 0:
#             print(f"  uncategorized: {results['statistics']['uncategorized_documents']:,} documents")
#
#         print(f"\n🌲 DEPTH DISTRIBUTION:")
#         for depth in sorted(results['statistics']['urls_by_depth'].keys()):
#             count = results['statistics']['urls_by_depth'][depth]
#             print(f"  Depth {depth}: {count:,} URLs")
#         print(f"\n📏 Maximum Depth: {results['statistics']['max_depth_reached']}")
#         print("=" * 70 + "\n")
#
#
# def crawl_website(base_url: str, allowed_subdomains: List[str], sections_for_docs: List[str] = None,
#                   output_dir: str = 'url_discovery', json_only: bool = False):
#     """
#     Crawl website with ONLY specified subdomains
#
#     Args:
#         base_url: Website base URL
#         allowed_subdomains: List of exact subdomains to crawl (e.g., ['www.srmist.edu.in', 'webstor.srmist.edu.in'])
#         sections_for_docs: List of keywords to categorize documents (optional)
#         output_dir: Directory to save results
#         json_only: If True, only save JSON files
#     """
#
#     print("\n" + "=" * 70)
#     print("🌐 OPTIMIZED WEBSITE CRAWL - SPECIFIC SUBDOMAINS ONLY")
#     print("=" * 70)
#     print(f"Website: {base_url}")
#     print(f"Allowed Subdomains: {', '.join(allowed_subdomains)}")
#     if sections_for_docs:
#         print(f"Document Categories: {', '.join(sections_for_docs)}")
#     print()
#
#     config = {
#         'max_depth': 5,
#         'max_urls': None,
#         'delay': 0.2,
#         'timeout': 10,
#         'use_head_requests': True,
#         'target_sections': sections_for_docs or [],
#         'allowed_subdomains': allowed_subdomains,  # CRITICAL: Only these will be crawled
#         'document_extensions': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'],
#         'exclude_patterns': [
#             '/wp-admin/',
#             '/wp-content/plugins/',
#             '/cdn-cgi/',
#         ]
#     }
#
#     counter = FastURLCounter(base_url, config)
#     results = counter.count_urls()
#     counter.print_summary(results)
#     saved_files = counter.save_results(results, output_dir=output_dir, save_json_only=json_only)
#
#     print("\n📁 FILES SAVED:")
#     for file_type, filepath in saved_files.items():
#         print(f"  {file_type}: {filepath}")
#
#     return results
#
#
# def main():
#     """Crawl website with specific subdomains only"""
#
#     START_URL = "https://www.srmist.edu.in/"
#
#     # CRITICAL: Only these exact subdomains will be crawled
#     ALLOWED_SUBDOMAINS = [
#         'www.srmist.edu.in',
#         'webstor.srmist.edu.in',
#         # 'applications.srmist.edu.in',
#         # 'dental.srmist.edu.in',
#         # 'medical.srmist.edu.in',
#     ]
#
#     DOCUMENT_CATEGORIES = [
#         'admission', 'admissions',
#         'hostel', 'hostels',
#         'placement', 'placements',
#         'event', 'events',
#         'alumni', 'alumnis',
#         'examination', 'examinations',
#         'academic', 'academics',
#         'research',
#         'faculty',
#         'student',
#         'campus',
#         'scholarship', 'scholarships',
#         'curriculum',
#         'syllabus',
#         'staff'
#     ]
#
#     results = crawl_website(
#         base_url=START_URL,
#         allowed_subdomains=ALLOWED_SUBDOMAINS,
#         sections_for_docs=DOCUMENT_CATEGORIES,
#         output_dir='optimized_crawl',
#         json_only=False
#     )
#
#     print(f"\n✅ CRAWL COMPLETE!")
#     print(f"   Total URLs: {results['statistics']['total_internal_urls']}")
#     print(f"   HTML Pages: {results['statistics']['total_html_urls']}")
#     print(f"   Document Files: {results['statistics']['total_document_urls']}")
#     print(f"   Subdomains Crawled: {', '.join(results['subdomains_found'])}")
#
#     return results
#
#
# if __name__ == '__main__':
#     main()


import requests
import time
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from collections import deque, defaultdict
from datetime import datetime
from typing import Set, Dict, List, Tuple
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class FastURLCounter:
    """Lightweight URL discovery and counter with specific subdomain control"""

    def __init__(self, start_url: str, config: Dict = None):
        self.start_url = start_url
        parsed = urlparse(start_url)
        self.domain = parsed.netloc
        self.base_scheme = parsed.scheme

        # Extract base domain for subdomain matching
        domain_parts = self.domain.split('.')
        if len(domain_parts) >= 2:
            self.base_domain = '.'.join(domain_parts[-2:])
        else:
            self.base_domain = self.domain

        # Default configuration
        self.config = {
            'max_depth': 6,
            'timeout': 10,
            'delay': 0.3,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'exclude_extensions': [
                '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico',
                '.zip', '.mp4', '.mp3', '.avi', '.mov',
                '.css', '.js', '.woff', '.woff2', '.ttf', '.eot'
            ],
            'exclude_patterns': [
                '/wp-admin/', '/wp-content/uploads/',
                '/cdn-cgi/', '/assets/images/'
            ],
            'include_patterns': [],
            'max_urls': None,
            'use_head_requests': True,
            'target_sections': [],
            'allowed_subdomains': [],  # ONLY these subdomains will be crawled
            'document_extensions': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
        }

        if config:
            self.config.update(config)

        # Normalize allowed subdomains to lowercase
        self.allowed_subdomains = set(s.lower() for s in self.config['allowed_subdomains'])

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config['user_agent'],
        })

        # State tracking
        self.urls_to_visit = deque([(start_url, 0)])
        self.visited_urls: Set[str] = set()
        self.internal_urls: Set[str] = set()
        self.external_urls: Set[str] = set()
        self.failed_urls: Set[str] = set()
        self.url_metadata: Dict[str, Dict] = {}
        self.urls_by_depth: Dict[int, List[str]] = {}

        # Document tracking
        self.document_urls: Set[str] = set()
        self.pdf_urls: Set[str] = set()  # NEW: Separate PDF tracking
        self.documents_by_type: Dict[str, List[str]] = defaultdict(list)
        self.documents_by_section: Dict[str, List[str]] = defaultdict(list)
        self.uncategorized_documents: List[str] = []
        self.html_urls: Set[str] = set()

        # Subdomain tracking
        self.subdomains_found: Set[str] = set()
        self.blocked_subdomains: Set[str] = set()  # Track rejected subdomains

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for consistent comparison"""
        try:
            parsed = urlparse(url)
            normalized = urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path.rstrip('/') if parsed.path != '/' else '/',
                parsed.params,
                parsed.query,
                ''
            ))
            return normalized
        except:
            return url

    def _is_allowed_domain(self, url: str) -> bool:
        """
        Check if URL belongs to an allowed subdomain
        CRITICAL: Only crawl URLs from explicitly allowed subdomains
        """
        try:
            parsed = urlparse(url)
            url_domain = parsed.netloc.lower()

            # Check if this exact domain is in allowed list
            is_allowed = url_domain in self.allowed_subdomains

            if not is_allowed:
                # Track blocked subdomains for reporting
                if url_domain.endswith('.' + self.base_domain) or url_domain == self.base_domain:
                    self.blocked_subdomains.add(url_domain)

            return is_allowed
        except:
            return False

    def _is_document_url(self, url: str, content_type: str = None) -> Tuple[bool, str]:
        """Check if URL points to a document and return (is_document, extension)"""
        url_lower = url.lower()

        # Check file extension
        for ext in self.config['document_extensions']:
            if url_lower.endswith(ext):
                return (True, ext.lstrip('.'))

        # Check content type if available
        if content_type:
            content_type_lower = content_type.lower()
            doc_types = {
                'application/pdf': 'pdf',
                'application/vnd.ms-excel': 'xls',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
                'application/msword': 'doc',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
                'application/vnd.ms-powerpoint': 'ppt',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx'
            }
            for mime_type, ext in doc_types.items():
                if mime_type in content_type_lower:
                    return (True, ext)

        return (False, '')

    def _categorize_document(self, url: str) -> str:
        """Determine which section a document belongs to"""
        url_lower = url.lower()

        for section in self.config['target_sections']:
            if section.lower() in url_lower:
                return section

        return 'uncategorized'

    def _is_valid_url(self, url: str, depth: int) -> bool:
        """Check if URL should be processed"""
        try:
            parsed = urlparse(url)

            # CRITICAL: Must be an allowed subdomain
            if not self._is_allowed_domain(url):
                return False

            # Check depth
            if depth >= self.config['max_depth']:
                return False

            # Check if it's a document - documents are always valid
            is_doc, _ = self._is_document_url(url)

            if not is_doc:
                # Check extensions for non-document files
                path = parsed.path.lower()
                if any(path.endswith(ext) for ext in self.config['exclude_extensions']):
                    return False

            # Check exclude patterns
            if any(pattern in url for pattern in self.config['exclude_patterns']):
                return False

            return True
        except:
            return False

    def _extract_links(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """Extract all links from page"""
        links = []

        for link_tag in soup.find_all('a', href=True):
            href = link_tag['href'].strip()

            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue

            absolute_url = urljoin(current_url, href)
            normalized = self._normalize_url(absolute_url)
            links.append(normalized)

        return links

    def count_urls(self) -> Dict:
        """Main counting method - discovers URLs from allowed subdomains only"""
        logger.info(f" Starting crawl for: {self.start_url}")
        logger.info(f" ALLOWED subdomains: {', '.join(sorted(self.allowed_subdomains))}")
        logger.info(f"Config: max_depth={self.config['max_depth']}, max_urls={self.config['max_urls']}")

        if self.config['target_sections']:
            logger.info(f" Document categorization: {', '.join(self.config['target_sections'])}")

        start_time = datetime.now()
        processed = 0

        while self.urls_to_visit:
            if self.config['max_urls'] and processed >= self.config['max_urls']:
                logger.info(f"Reached max URL limit: {self.config['max_urls']}")
                break

            current_url, depth = self.urls_to_visit.popleft()
            current_url = self._normalize_url(current_url)

            if current_url in self.visited_urls:
                continue

            self.visited_urls.add(current_url)
            self.internal_urls.add(current_url)
            processed += 1

            # Track subdomain
            parsed = urlparse(current_url)
            self.subdomains_found.add(parsed.netloc)

            if depth not in self.urls_by_depth:
                self.urls_by_depth[depth] = []
            self.urls_by_depth[depth].append(current_url)

            if processed % 50 == 0:
                logger.info(
                    f"Progress: {processed} URLs | Queue: {len(self.urls_to_visit)} | "
                    f"Docs: {len(self.document_urls)} | PDFs: {len(self.pdf_urls)} | Depth: {depth}"
                )

            try:
                status_code = None
                content_type = None

                if self.config['use_head_requests']:
                    try:
                        response = self.session.head(
                            current_url,
                            timeout=self.config['timeout'],
                            allow_redirects=True
                        )
                        status_code = response.status_code
                        content_type = response.headers.get('Content-Type', '')
                    except:
                        pass

                if status_code is None:
                    response = self.session.get(
                        current_url,
                        timeout=self.config['timeout']
                    )
                    status_code = response.status_code
                    content_type = response.headers.get('Content-Type', '')

                # Check if it's a document
                is_document, doc_type = self._is_document_url(current_url, content_type)

                self.url_metadata[current_url] = {
                    'status_code': status_code,
                    'content_type': content_type,
                    'depth': depth,
                    'is_document': is_document,
                    'document_type': doc_type if is_document else None
                }

                if status_code != 200:
                    logger.debug(f"Status {status_code}: {current_url}")
                    self.failed_urls.add(current_url)
                    continue

                # Categorize documents
                if is_document:
                    self.document_urls.add(current_url)
                    self.documents_by_type[doc_type].append(current_url)

                    # NEW: Track PDFs separately
                    if doc_type == 'pdf':
                        self.pdf_urls.add(current_url)

                    section = self._categorize_document(current_url)

                    if section == 'uncategorized':
                        self.uncategorized_documents.append(current_url)
                    else:
                        self.documents_by_section[section].append(current_url)

                    logger.debug(f" {doc_type.upper()} found [{section}]: {current_url}")
                    continue

                # Track HTML pages
                if 'text/html' in content_type.lower():
                    self.html_urls.add(current_url)

                # Extract links only from HTML pages
                if 'text/html' in content_type.lower() and depth < self.config['max_depth'] - 1:
                    if response.request.method == 'HEAD':
                        response = self.session.get(
                            current_url,
                            timeout=self.config['timeout']
                        )

                    soup = BeautifulSoup(response.content, 'html.parser')
                    links = self._extract_links(soup, current_url)

                    for link in links:
                        if self._is_allowed_domain(link):
                            if (link not in self.visited_urls and
                                    self._is_valid_url(link, depth + 1)):
                                self.urls_to_visit.append((link, depth + 1))
                        else:
                            self.external_urls.add(link)

                time.sleep(self.config['delay'])

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout: {current_url}")
                self.failed_urls.add(current_url)
            except Exception as e:
                logger.warning(f"Error processing {current_url}: {str(e)[:100]}")
                self.failed_urls.add(current_url)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Build results
        results = {
            'domain': self.domain,
            'base_domain': self.base_domain,
            'allowed_subdomains': sorted(list(self.allowed_subdomains)),
            'subdomains_found': sorted(list(self.subdomains_found)),
            'blocked_subdomains': sorted(list(self.blocked_subdomains)),
            'start_url': self.start_url,
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': round(duration, 2),
            'urls_per_second': round(processed / duration, 2) if duration > 0 else 0,
            'statistics': {
                'total_internal_urls': len(self.internal_urls),
                'total_external_urls': len(self.external_urls),
                'total_failed_urls': len(self.failed_urls),
                'total_discovered': len(self.internal_urls) + len(self.external_urls),
                'total_document_urls': len(self.document_urls),
                'total_pdf_urls': len(self.pdf_urls),  # NEW: PDF count
                'total_html_urls': len(self.html_urls),
                'max_depth_reached': max(self.urls_by_depth.keys()) if self.urls_by_depth else 0,
                'urls_by_depth': {
                    depth: len(urls) for depth, urls in self.urls_by_depth.items()
                },
                'documents_by_type': {
                    doc_type: len(urls) for doc_type, urls in self.documents_by_type.items()
                },
                'documents_by_section': {
                    section: len(urls) for section, urls in self.documents_by_section.items()
                },
                'uncategorized_documents': len(self.uncategorized_documents)
            },
            'urls': {
                'internal': sorted(list(self.internal_urls)),
                'external': sorted(list(self.external_urls)),
                'failed': sorted(list(self.failed_urls)),
                'documents_all': sorted(list(self.document_urls)),
                'pdf_only': sorted(list(self.pdf_urls)),  # NEW: PDFs only
                'html': sorted(list(self.html_urls))
            },
            'documents_by_type': {
                doc_type: sorted(urls) for doc_type, urls in self.documents_by_type.items()
            },
            'documents_by_section': {
                section: sorted(urls) for section, urls in self.documents_by_section.items()
            },
            'uncategorized_documents': sorted(self.uncategorized_documents),
            'metadata': self.url_metadata
        }

        logger.info(f" Discovery complete in {duration:.2f} seconds")
        logger.info(f" Found {len(self.document_urls)} documents ({len(self.pdf_urls)} PDFs)")
        if self.blocked_subdomains:
            logger.info(
                f" Blocked {len(self.blocked_subdomains)} subdomains: {', '.join(sorted(list(self.blocked_subdomains))[:5])}")

        return results

    def save_results(self, results: Dict, output_dir: str = 'url_discovery', save_json_only: bool = False):
        """Save results to files"""
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        domain_name = self.domain.replace('.', '_')

        saved_files = {}

        # Always save complete results as JSON
        json_file = os.path.join(output_dir, f"{domain_name}_complete_{timestamp}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        saved_files['complete_json'] = json_file

        # Save separate JSON files
        json_dir = os.path.join(output_dir, 'json_results')
        os.makedirs(json_dir, exist_ok=True)

        # HTML URLs JSON
        html_json = os.path.join(json_dir, f"{domain_name}_html_pages_{timestamp}.json")
        with open(html_json, 'w', encoding='utf-8') as f:
            json.dump({
                'domain': self.domain,
                'timestamp': results['timestamp'],
                'total_count': len(results['urls']['html']),
                'urls': results['urls']['html']
            }, f, indent=2, ensure_ascii=False)
        saved_files['html_json'] = html_json

        # All Documents JSON
        all_docs_json = os.path.join(json_dir, f"{domain_name}_all_documents_{timestamp}.json")
        with open(all_docs_json, 'w', encoding='utf-8') as f:
            json.dump({
                'domain': self.domain,
                'timestamp': results['timestamp'],
                'total_count': len(results['urls']['documents_all']),
                'urls': results['urls']['documents_all']
            }, f, indent=2, ensure_ascii=False)
        saved_files['all_documents_json'] = all_docs_json

        # NEW: PDF-ONLY JSON (Separate file for PDFs)
        pdf_only_json = os.path.join(json_dir, f"{domain_name}_PDF_ONLY_{timestamp}.json")
        with open(pdf_only_json, 'w', encoding='utf-8') as f:
            json.dump({
                'domain': self.domain,
                'timestamp': results['timestamp'],
                'total_pdf_count': len(results['urls']['pdf_only']),
                'pdf_urls': results['urls']['pdf_only']
            }, f, indent=2, ensure_ascii=False)
        saved_files['pdf_only_json'] = pdf_only_json
        logger.info(f" Saved {len(results['urls']['pdf_only'])} PDFs to: {pdf_only_json}")

        # Documents by type JSON
        docs_by_type_json = os.path.join(json_dir, f"{domain_name}_documents_by_type_{timestamp}.json")
        with open(docs_by_type_json, 'w', encoding='utf-8') as f:
            json.dump({
                'domain': self.domain,
                'timestamp': results['timestamp'],
                'types': {
                    doc_type: {
                        'count': len(urls),
                        'urls': urls
                    } for doc_type, urls in results['documents_by_type'].items()
                }
            }, f, indent=2, ensure_ascii=False)
        saved_files['documents_by_type_json'] = docs_by_type_json

        # Documents by section JSON
        docs_by_section_json = os.path.join(json_dir, f"{domain_name}_documents_by_section_{timestamp}.json")
        docs_section_data = {
            'domain': self.domain,
            'timestamp': results['timestamp'],
            'sections': {}
        }
        for section, urls in results['documents_by_section'].items():
            docs_section_data['sections'][section] = {
                'count': len(urls),
                'urls': urls
            }
        if results['uncategorized_documents']:
            docs_section_data['sections']['uncategorized'] = {
                'count': len(results['uncategorized_documents']),
                'urls': results['uncategorized_documents']
            }

        with open(docs_by_section_json, 'w', encoding='utf-8') as f:
            json.dump(docs_section_data, f, indent=2, ensure_ascii=False)
        saved_files['documents_by_section_json'] = docs_by_section_json

        # Statistics JSON
        stats_json = os.path.join(json_dir, f"{domain_name}_statistics_{timestamp}.json")
        with open(stats_json, 'w', encoding='utf-8') as f:
            json.dump(results['statistics'], f, indent=2, ensure_ascii=False)
        saved_files['statistics_json'] = stats_json

        if save_json_only:
            return saved_files

        # Save text files for convenience
        internal_file = os.path.join(output_dir, f"{domain_name}_internal_{timestamp}.txt")
        with open(internal_file, 'w', encoding='utf-8') as f:
            f.write(f"# Internal URLs for {self.domain}\n")
            f.write(f"# Total: {results['statistics']['total_internal_urls']}\n")
            f.write(f"# Generated: {results['timestamp']}\n\n")
            for url in results['urls']['internal']:
                f.write(f"{url}\n")
        saved_files['internal_urls'] = internal_file

        # NEW: PDF-only text file
        pdf_txt_file = os.path.join(output_dir, f"{domain_name}_PDF_ONLY_{timestamp}.txt")
        with open(pdf_txt_file, 'w', encoding='utf-8') as f:
            f.write(f"# PDF Files for {self.domain}\n")
            f.write(f"# Total: {results['statistics']['total_pdf_urls']}\n")
            f.write(f"# Generated: {results['timestamp']}\n\n")
            for url in results['urls']['pdf_only']:
                f.write(f"{url}\n")
        saved_files['pdf_only_txt'] = pdf_txt_file

        return saved_files

    def print_summary(self, results: Dict):
        """Print results summary to console"""
        print("\n" + "=" * 70)
        print(" URL DISCOVERY COMPLETE")
        print("=" * 70)
        print(f"Domain: {results['domain']}")
        print(f"Allowed Subdomains: {', '.join(results['allowed_subdomains'])}")
        print(f"Subdomains Crawled: {', '.join(results['subdomains_found'])}")
        if results['blocked_subdomains']:
            print(f"Blocked Subdomains: {', '.join(results['blocked_subdomains'][:5])}")
        print(f"Duration: {results['duration_seconds']} seconds")
        print(f"Speed: {results['urls_per_second']} URLs/second")
        print("\n STATISTICS:")
        print(f"  Internal URLs: {results['statistics']['total_internal_urls']:,}")
        print(f"  HTML Pages: {results['statistics']['total_html_urls']:,}")
        print(f"  Document Files: {results['statistics']['total_document_urls']:,}")
        print(f"   PDF Files: {results['statistics']['total_pdf_urls']:,}")  # NEW: PDF count
        print(f"  External URLs: {results['statistics']['total_external_urls']:,}")
        print(f"  Failed URLs: {results['statistics']['total_failed_urls']:,}")

        if results['statistics']['documents_by_type']:
            print(f"\n DOCUMENTS BY TYPE:")
            for doc_type in sorted(results['statistics']['documents_by_type'].keys()):
                count = results['statistics']['documents_by_type'][doc_type]
                print(f"  {doc_type.upper()}: {count:,} files")

        if results['statistics']['documents_by_section']:
            print(f"\n DOCUMENTS BY SECTION:")
            for section in sorted(results['statistics']['documents_by_section'].keys()):
                count = results['statistics']['documents_by_section'][section]
                print(f"  {section}: {count:,} documents")
        if results['statistics']['uncategorized_documents'] > 0:
            print(f"  uncategorized: {results['statistics']['uncategorized_documents']:,} documents")

        print(f"\n DEPTH DISTRIBUTION:")
        for depth in sorted(results['statistics']['urls_by_depth'].keys()):
            count = results['statistics']['urls_by_depth'][depth]
            print(f"  Depth {depth}: {count:,} URLs")
        print(f"\n Maximum Depth: {results['statistics']['max_depth_reached']}")
        print("=" * 70 + "\n")


def crawl_website(base_url: str, allowed_subdomains: List[str], sections_for_docs: List[str] = None,
                  output_dir: str = 'url_discovery', json_only: bool = False):
    """
    Crawl website with ONLY specified subdomains

    Args:
        base_url: Website base URL
        allowed_subdomains: List of exact subdomains to crawl (e.g., ['www.srmist.edu.in', 'webstor.srmist.edu.in'])
        sections_for_docs: List of keywords to categorize documents (optional)
        output_dir: Directory to save results
        json_only: If True, only save JSON files
    """

    print("\n" + "=" * 70)
    print(" OPTIMIZED WEBSITE CRAWL - SPECIFIC SUBDOMAINS ONLY")
    print("=" * 70)
    print(f"Website: {base_url}")
    print(f"Allowed Subdomains: {', '.join(allowed_subdomains)}")
    if sections_for_docs:
        print(f"Document Categories: {', '.join(sections_for_docs)}")
    print()

    config = {
        'max_depth': 5,
        'max_urls': None,
        'delay': 0.2,
        'timeout': 10,
        'use_head_requests': True,
        'target_sections': sections_for_docs or [],
        'allowed_subdomains': allowed_subdomains,  # CRITICAL: Only these will be crawled
        'document_extensions': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'],
        'exclude_patterns': [
            '/wp-admin/',
            '/wp-content/plugins/',
            '/cdn-cgi/',
        ]
    }

    counter = FastURLCounter(base_url, config)
    results = counter.count_urls()
    counter.print_summary(results)
    saved_files = counter.save_results(results, output_dir=output_dir, save_json_only=json_only)

    print("\n FILES SAVED:")
    for file_type, filepath in saved_files.items():
        print(f"  {file_type}: {filepath}")

    return results


def main():
    """Crawl website with specific subdomains only"""

    START_URL = "https://www.srmist.edu.in/"

    # CRITICAL: Only these exact subdomains will be crawled
    ALLOWED_SUBDOMAINS = [
        'www.srmist.edu.in',
        'webstor.srmist.edu.in',
        # 'applications.srmist.edu.in',
        # 'dental.srmist.edu.in',
        # 'medical.srmist.edu.in',
    ]

    DOCUMENT_CATEGORIES = [
        'admission', 'admissions',
        'hostel', 'hostels',
        'placement', 'placements',
        'event', 'events',
        'alumni', 'alumnis',
        'examination', 'examinations',
        'academic', 'academics',
        'research',
        'faculty',
        'student',
        'campus',
        'scholarship', 'scholarships',
        'curriculum',
        'syllabus',
        'staff'
    ]

    results = crawl_website(
        base_url=START_URL,
        allowed_subdomains=ALLOWED_SUBDOMAINS,
        sections_for_docs=DOCUMENT_CATEGORIES,
        output_dir='pdf_urls',
        json_only=False
    )

    print(f"\n CRAWL COMPLETE!")
    print(f"   Total URLs: {results['statistics']['total_internal_urls']}")
    print(f"   HTML Pages: {results['statistics']['total_html_urls']}")
    print(f"   Document Files: {results['statistics']['total_document_urls']}")
    print(f"    PDF Files: {results['statistics']['total_pdf_urls']}")  # NEW: PDF count
    print(f"   Subdomains Crawled: {', '.join(results['subdomains_found'])}")

    return results


if __name__ == '__main__':
    main()