import socket
import pytest
from unittest.mock import patch
from core.dns_resolver import (
    build_dns_query,
    parse_dns_response,
    resolve_host_with_fallback,
    smart_getaddrinfo,
    install_smart_dns,
    _DNS_CACHE
)

def test_build_dns_query():
    query = build_dns_query("example.com")
    assert isinstance(query, bytes)
    assert len(query) > 12
    # Ensure domain components are encoded
    assert b"example" in query
    assert b"com" in query

def test_parse_dns_response_empty():
    res = parse_dns_response(b"")
    assert res == []

def test_resolve_host_fallback_static():
    ip = resolve_host_with_fallback("d237157.fpvcdn.com")
    assert ip == "50.7.252.210"

def test_resolve_host_wildcard_fpvcdn():
    ip = resolve_host_with_fallback("test-subdomain.fpvcdn.com")
    assert ip == "50.7.252.210"

def test_smart_getaddrinfo_fallback():
    install_smart_dns()
    # Resolve host that might otherwise fail standard getaddrinfo
    info = socket.getaddrinfo("d237157.fpvcdn.com", 443)
    assert len(info) > 0
    # Destination IP must be the mapped IP
    assert info[0][4][0] == "50.7.252.210"
    assert info[0][4][1] == 443
