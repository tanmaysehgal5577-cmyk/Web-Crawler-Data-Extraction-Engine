"""
Utilities/constants.py
Project-wide constants for CrawlMind.
"""

# Package version
VERSION = "1.0.0"
PARSER_VERSION = "1.0.0"
EXTRACTION_VERSION = "1.0.0"

# Tracking / noise query params to strip from URLs
TRACKING_PARAMS: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "msclkid", "twclid", "li_fat_id", "mc_eid",
    "igshid", "yclid", "dclid", "_ga", "_gl",
    "ref", "referrer", "source",
})

# URL schemes accepted by the crawler
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Schemes that must be blocked immediately
BLOCKED_SCHEMES: frozenset[str] = frozenset({
    "javascript", "data", "file", "ftp", "mailto", "tel", "blob",
})

# MIME types considered HTML (worth parsing)
HTML_CONTENT_TYPES: frozenset[str] = frozenset({
    "text/html", "application/xhtml+xml",
})

# File extensions that are definitely not HTML pages
NON_HTML_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z",
    ".exe", ".msi", ".dmg", ".deb", ".rpm",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".webm", ".ogg", ".wav",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".xml",  # too broad but safe default; remove if you need to crawl sitemaps
    ".json",
    ".csv",
    ".txt",
})

# HTTP status codes that are transient (worth retrying)
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

# HTTP status codes for "not found" — do not retry
PERMANENT_ERROR_STATUS_CODES: frozenset[int] = frozenset({
    400, 401, 403, 404, 405, 406, 410, 414, 422, 451,
})

# Private / loopback / link-local / special-purpose CIDRs (IPv4)
PRIVATE_IPV4_RANGES: tuple[tuple[int, int], ...] = (
    (0x00000000, 0xFF000000),        # 0.0.0.0/8
    (0x0A000000, 0xFF000000),        # 10.0.0.0/8
    (0x64400000, 0xFFC00000),        # 100.64.0.0/10  (carrier-grade NAT)
    (0x7F000000, 0xFF000000),        # 127.0.0.0/8    (loopback)
    (0xA9FE0000, 0xFFFF0000),        # 169.254.0.0/16 (link-local / metadata)
    (0xAC100000, 0xFFF00000),        # 172.16.0.0/12
    (0xC0000000, 0xFFFFFF00),        # 192.0.0.0/24
    (0xC00000AA, 0xFFFFFFFE),        # 192.0.0.170/31
    (0xC0000200, 0xFFFFFF00),        # 192.0.2.0/24  (TEST-NET-1)
    (0xC0A80000, 0xFFFF0000),        # 192.168.0.0/16
    (0xC6120000, 0xFFFE0000),        # 198.18.0.0/15
    (0xC6336400, 0xFFFFFF00),        # 198.51.100.0/24 (TEST-NET-2)
    (0xCB007100, 0xFFFFFF00),        # 203.0.113.0/24  (TEST-NET-3)
    (0xE0000000, 0xF0000000),        # 224.0.0.0/4    (multicast)
    (0xF0000000, 0xF0000000),        # 240.0.0.0/4    (reserved)
    (0xFFFFFFFF, 0xFFFFFFFF),        # 255.255.255.255
)

# Sitemap limits per spec
SITEMAP_MAX_URLS = 50_000
SITEMAP_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# FTS5 stop-words (English, minimal set)
FTS5_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "not", "no", "it", "its",
    "this", "that", "as", "if", "so", "we", "you", "he", "she", "they",
})

# Crawl task priority levels
PRIORITY_SEED = 0
PRIORITY_NORMAL = 10
PRIORITY_DEPTH_PENALTY = 5  # added per depth level

# Max repeated path segments before flagging as trap
MAX_REPEATED_SEGMENT_OCCURRENCES = 3

# Robots.txt cache TTL (seconds)
ROBOTS_CACHE_TTL = 3600  # 1 hour

# DB schema version
SCHEMA_VERSION = 3
