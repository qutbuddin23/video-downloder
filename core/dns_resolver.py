"""
Smart Resilient DNS Resolver for Universal Video Downloader.
Bypasses ISP DNS blocking, NXDOMAIN errors, and registrar client-holds
by querying authoritative nameservers and public DNS providers directly over standard UDP port 53.
Zero external dependencies (pure Python standard library socket + struct).
"""

import socket
import struct
import threading
from typing import Optional, List, Dict

_LOCK = threading.Lock()
_ORIG_GETADDRINFO = socket.getaddrinfo
_SMART_DNS_INSTALLED = False

# In-memory resolved IP cache
_DNS_CACHE: Dict[str, str] = {
    # Hardcoded fallback mappings for known CDN platforms
    "d237157.fpvcdn.com": "50.7.252.210",
}

# Reliable authoritative and public DNS servers
FALLBACK_DNS_SERVERS = (
    # Cloudflare Authoritative Nameservers (fpvcdn.com)
    "173.245.58.55",
    "172.64.32.55",
    # Cloudflare Public Anycast DNS
    "1.1.1.1",
    "1.0.0.1",
    # Google Public Anycast DNS
    "8.8.8.8",
    "8.8.4.4",
    # Quad9 Anycast DNS
    "9.9.9.9",
    # OpenDNS
    "208.67.222.222",
)


def build_dns_query(domain: str) -> bytes:
    """Constructs a standard DNS A-record query packet."""
    tid = b"\x12\x34"
    flags = b"\x01\x00"  # Standard recursive query
    counts = struct.pack("!HHHH", 1, 0, 0, 0)
    qname = b""
    for part in domain.split("."):
        if part:
            qname += bytes([len(part)]) + part.encode("ascii", errors="replace")
    qname += b"\x00"
    qtype_qclass = struct.pack("!HH", 1, 1)  # A record, IN class
    return tid + flags + counts + qname + qtype_qclass


def parse_dns_response(data: bytes) -> List[str]:
    """Parses IPv4 addresses from a raw DNS response packet."""
    if len(data) < 12:
        return []
    ancount = struct.unpack("!H", data[6:8])[0]
    if ancount == 0:
        return []

    # Skip header (12 bytes) and question section
    offset = 12
    while offset < len(data) and data[offset] != 0:
        offset += 1 + data[offset]
    offset += 5  # Skip trailing null byte and qtype/qclass

    ips = []
    for _ in range(ancount):
        if offset >= len(data):
            break
        # Check domain name (compressed pointer 0xC0 or standard label)
        if (data[offset] & 0xC0) == 0xC0:
            offset += 2
        else:
            while offset < len(data) and data[offset] != 0:
                offset += 1 + data[offset]
            offset += 1

        if offset + 10 > len(data):
            break
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == 1 and rdlen == 4 and offset + 4 <= len(data):  # A record (IPv4)
            ip = socket.inet_ntoa(data[offset:offset + 4])
            ips.append(ip)
        offset += rdlen

    return ips


def query_udp_dns(server_ip: str, domain: str, timeout: float = 2.0) -> List[str]:
    """Queries a specific DNS server over UDP port 53."""
    try:
        query_bytes = build_dns_query(domain)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(query_bytes, (server_ip, 53))
        resp, _ = s.recvfrom(2048)
        s.close()
        return parse_dns_response(resp)
    except Exception:
        return []


def resolve_host_with_fallback(host: str) -> Optional[str]:
    """
    Attempts to resolve host using in-memory cache, static mappings,
    or direct UDP queries against authoritative and public DNS providers.
    """
    if not host or not isinstance(host, str):
        return None

    clean_host = host.strip().lower()

    # 1. Check in-memory cache
    with _LOCK:
        if clean_host in _DNS_CACHE:
            return _DNS_CACHE[clean_host]

        # Check wildcard pattern for fpvcdn.com
        if clean_host.endswith(".fpvcdn.com") or clean_host == "fpvcdn.com":
            _DNS_CACHE[clean_host] = "50.7.252.210"
            return "50.7.252.210"

    # 2. Query fallback DNS servers in order
    for server_ip in FALLBACK_DNS_SERVERS:
        ips = query_udp_dns(server_ip, clean_host, timeout=2.0)
        if ips and ips[0] and not ips[0].startswith("0.") and not ips[0].startswith("127."):
            chosen_ip = ips[0]
            with _LOCK:
                _DNS_CACHE[clean_host] = chosen_ip
            print(f"[SmartDNS] Successfully resolved '{clean_host}' -> {chosen_ip} via DNS server {server_ip}")
            return chosen_ip

    return None


def smart_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """
    Hooked socket.getaddrinfo that transparently resolves blocked or client-held
    domains via authoritative/fallback DNS queries.
    """
    try:
        return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
    except (socket.gaierror, OSError) as orig_err:
        # Fallback to Smart DNS Resolver
        if isinstance(host, str) and not host.replace(".", "").isdigit():
            resolved_ip = resolve_host_with_fallback(host)
            if resolved_ip:
                try:
                    return _ORIG_GETADDRINFO(resolved_ip, port, family, type, proto, flags)
                except Exception:
                    pass
        raise orig_err


def install_smart_dns():
    """Activates the Smart Resilient DNS Resolver globally across the Python process."""
    global _SMART_DNS_INSTALLED
    with _LOCK:
        if not _SMART_DNS_INSTALLED:
            socket.getaddrinfo = smart_getaddrinfo
            _SMART_DNS_INSTALLED = True
            print("[SmartDNS] Global resilient DNS resolver installed.")
