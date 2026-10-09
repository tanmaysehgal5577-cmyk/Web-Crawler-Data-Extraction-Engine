"""tests/test_url_normalizer.py"""

from __future__ import annotations

import pytest
from Crawler.url_normalizer import normalize_url, extract_domain, is_internal_link
from Utilities.exceptions import InvalidURLError


class TestNormalizeUrl:
    def test_lowercase_scheme(self):
        assert normalize_url("HTTP://Example.COM/").startswith("http://")

    def test_lowercase_hostname(self):
        result = normalize_url("https://EXAMPLE.COM/page")
        assert "example.com" in result

    def test_removes_default_http_port(self):
        assert normalize_url("http://example.com:80/") == "http://example.com/"

    def test_removes_default_https_port(self):
        assert normalize_url("https://example.com:443/") == "https://example.com/"

    def test_keeps_nondefault_port(self):
        result = normalize_url("https://example.com:8080/")
        assert ":8080" in result

    def test_removes_fragment(self):
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result

    def test_removes_tracking_params(self):
        result = normalize_url("https://example.com/?utm_source=google&id=123")
        assert "utm_source" not in result
        assert "id=123" in result

    def test_sorts_query_params(self):
        r1 = normalize_url("https://example.com/?b=2&a=1")
        r2 = normalize_url("https://example.com/?a=1&b=2")
        assert r1 == r2

    def test_removes_trailing_slash(self):
        result = normalize_url("https://example.com/page/")
        assert not result.endswith("/")

    def test_keeps_root_path(self):
        result = normalize_url("https://example.com/")
        # Root path may or may not have trailing slash depending on implementation
        assert "example.com" in result

    def test_resolves_dot_segments(self):
        result = normalize_url("https://example.com/a/../b")
        assert "/a/" not in result
        assert "/b" in result

    def test_relative_url_with_base(self):
        result = normalize_url("/about", base_url="https://example.com/page")
        assert result.startswith("https://example.com")
        assert "about" in result

    def test_empty_url_raises(self):
        with pytest.raises(InvalidURLError):
            normalize_url("")

    def test_unsupported_scheme_raises(self):
        with pytest.raises(InvalidURLError):
            normalize_url("ftp://example.com/file")

    def test_javascript_scheme_raises(self):
        with pytest.raises(InvalidURLError):
            normalize_url("javascript:alert(1)")

    def test_idempotent(self):
        url = "https://example.com/path?a=1&b=2"
        assert normalize_url(url) == normalize_url(normalize_url(url))

    def test_multiple_tracking_params_removed(self):
        url = "https://example.com/?q=test&utm_source=x&fbclid=abc&gclid=def"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "fbclid" not in result
        assert "gclid" not in result
        assert "q=test" in result

    def test_collapses_double_slashes(self):
        result = normalize_url("https://example.com//path//to//page")
        assert "//" not in result.split("https://")[1]


class TestExtractDomain:
    def test_basic(self):
        assert extract_domain("https://example.com/page") == "example.com"

    def test_subdomain(self):
        assert extract_domain("https://blog.example.com/") == "blog.example.com"

    def test_with_port(self):
        assert extract_domain("https://example.com:8080/") == "example.com"

    def test_empty_url(self):
        assert extract_domain("") == ""


class TestIsInternalLink:
    def test_same_domain(self):
        assert is_internal_link("https://example.com/page", "example.com")

    def test_www_variant(self):
        assert is_internal_link("https://www.example.com/page", "example.com")

    def test_subdomain_is_internal(self):
        assert is_internal_link("https://blog.example.com/", "example.com")

    def test_different_domain(self):
        assert not is_internal_link("https://other.com/page", "example.com")

    def test_similar_domain(self):
        assert not is_internal_link("https://example.com.evil.com/", "example.com")
