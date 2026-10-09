"""tests/test_security.py — SSRF protection tests."""

from __future__ import annotations

import pytest
from Utilities.security import validate_url_security, validate_ip
from Utilities.exceptions import SecurityValidationError


class TestValidateUrlSecurity:
    def test_valid_http_url(self):
        # Should not raise
        validate_url_security("http://example.com/page")

    def test_valid_https_url(self):
        validate_url_security("https://example.com/path?q=test")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(SecurityValidationError) as exc_info:
            validate_url_security("ftp://example.com/file")
        assert "scheme" in str(exc_info.value).lower()

    def test_rejects_file_scheme(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("file:///etc/passwd")

    def test_rejects_javascript_scheme(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("javascript:alert(1)")

    def test_rejects_data_scheme(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("data:text/html,<h1>test</h1>")

    def test_rejects_userinfo(self):
        with pytest.raises(SecurityValidationError) as exc_info:
            validate_url_security("https://user:pass@example.com/")
        assert "userinfo" in str(exc_info.value).lower()

    def test_rejects_userinfo_simple(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("https://user@example.com/")

    def test_rejects_localhost(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://127.0.0.1/admin", block_private_networks=True)

    def test_rejects_loopback(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://127.1.2.3/", block_private_networks=True)

    def test_rejects_private_rfc1918_10(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://10.0.0.1/api", block_private_networks=True)

    def test_rejects_private_rfc1918_172(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://172.16.0.1/", block_private_networks=True)

    def test_rejects_private_rfc1918_192(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://192.168.1.100/", block_private_networks=True)

    def test_rejects_metadata_service(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://169.254.169.254/latest/meta-data/", block_private_networks=True)

    def test_rejects_empty_url(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("")

    def test_rejects_invalid_port(self):
        with pytest.raises(ValueError):
            validate_url_security("https://example.com:99999/")

    def test_allows_private_when_disabled(self):
        # Should not raise when block_private_networks=False
        validate_url_security("http://127.0.0.1/", block_private_networks=False)

    def test_rejects_link_local(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://169.254.0.1/", block_private_networks=True)

    def test_rejects_multicast(self):
        with pytest.raises(SecurityValidationError):
            validate_url_security("http://224.0.0.1/", block_private_networks=True)


class TestValidateIp:
    def test_public_ipv4_allowed(self):
        # Should not raise
        validate_ip("8.8.8.8", url="http://8.8.8.8/")

    def test_loopback_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("127.0.0.1")

    def test_private_10_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("10.1.2.3")

    def test_private_172_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("172.20.0.1")

    def test_private_192_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("192.168.0.1")

    def test_metadata_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("169.254.169.254")

    def test_ipv6_loopback_blocked(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("::1")

    def test_invalid_ip_raises(self):
        with pytest.raises(SecurityValidationError):
            validate_ip("not_an_ip")
