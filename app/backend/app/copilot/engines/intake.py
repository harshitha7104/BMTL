"""
Safe intake for "anything" a user sends: folders (as .zip or a picked directory) and web links.

Archives (zip-bomb, path-traversal and symlink safe):
  - at most settings.zip_max_members files and settings.zip_max_total_mb uncompressed in total;
  - every member's compression ratio is capped (settings.zip_max_ratio) and its size is re-checked while
    reading, so a lying header cannot inflate past the limit;
  - member names are reduced to a sanitised basename (no paths are ever created from archive names);
  - nested archives, symlinks, encrypted members and OS junk (__MACOSX, .DS_Store) are skipped with a note.

Links (SSRF safe):
  - only http/https on ports 80/443, no credentials in the URL, optional allow/deny domain lists;
  - the host is resolved once and EVERY address must be public (no loopback, private, link-local,
    multicast, reserved or cloud-metadata ranges); the connection is then pinned to that vetted IP
    (Host header + TLS SNI keep the name), which defeats DNS-rebinding;
  - redirects are followed manually (max 3) and each hop is vetted again;
  - size cap while streaming, total timeout, and HTML is reduced to text (scripts/styles dropped).
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import stat
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from app.core.config import settings

UploadedFile = Tuple[str, str, bytes]
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
MAX_LINKS_PER_MESSAGE = 3
JUNK = ("__macosx/", ".ds_store", "thumbs.db", "desktop.ini")


class IntakeRejected(ValueError):
    """Input refused for safety reasons; the message is safe to show to the user."""


# --------------------------------------------------------------------------- archives
def is_archive(filename: str, data: bytes) -> bool:
    return filename.lower().endswith(".zip") or data[:4] == b"PK\x03\x04" and filename.lower().endswith((".zip", ".zipx"))


def expand_archive(data: bytes, filename: str) -> Tuple[List[UploadedFile], List[str]]:
    max_members = settings.zip_max_members
    max_total = settings.zip_max_total_mb * 1024 * 1024
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IntakeRejected(f"'{filename}' is not a readable zip archive") from exc
    members, notes, total = [], [], 0
    infos = zf.infolist()
    if len(infos) > max_members * 5:
        raise IntakeRejected(f"'{filename}' has {len(infos)} entries; the limit is {max_members}")
    for info in infos:
        name = info.filename.replace("\\", "/")
        lower = name.lower()
        if info.is_dir() or any(j in lower for j in JUNK):
            continue
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            notes.append(f"skipped symlink {name}")
            continue
        if info.flag_bits & 0x1:
            notes.append(f"skipped encrypted file {name}")
            continue
        base = PurePosixPath(name).name
        if base.lower().endswith((".zip", ".7z", ".rar", ".tar", ".gz")):
            notes.append(f"skipped nested archive {name}")
            continue
        if len(members) >= max_members:
            notes.append(f"stopped after {max_members} files")
            break
        if info.compress_size and info.file_size / max(info.compress_size, 1) > settings.zip_max_ratio:
            raise IntakeRejected(f"'{name}' in '{filename}' has a suspicious compression ratio (possible zip bomb)")
        if total + info.file_size > max_total:
            raise IntakeRejected(f"'{filename}' expands beyond {settings.zip_max_total_mb} MB")
        with zf.open(info) as fh:                      # re-check while reading: headers can lie
            chunk = fh.read(min(info.file_size, max_total - total) + 1)
        if len(chunk) > info.file_size or total + len(chunk) > max_total:
            raise IntakeRejected(f"'{name}' in '{filename}' is larger than its header claims")
        total += len(chunk)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:100] or "file"
        members.append((safe, "", chunk))
    if not members:
        notes.append("archive contained no usable files")
    return members, notes


# --------------------------------------------------------------------------- links
@dataclass
class FetchedLink:
    url: str
    filename: str
    content_type: str
    data: bytes


def extract_urls(message: str) -> List[str]:
    seen: List[str] = []
    for m in URL_RE.finditer(message or ""):
        url = m.group(0).rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
    return seen[:MAX_LINKS_PER_MESSAGE]


def _domain_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    deny = [d.strip().lower() for d in settings.link_blocked_domains.split(",") if d.strip()]
    allow = [d.strip().lower() for d in settings.link_allowed_domains.split(",") if d.strip()]
    if any(host == d or host.endswith("." + d) for d in deny):
        return False
    return not allow or any(host == d or host.endswith("." + d) for d in allow)


def vet_url(url: str) -> Tuple[str, str, int, str]:
    """(scheme, host, port, ip) for a URL that is safe to fetch, else IntakeRejected."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise IntakeRejected("only http(s) links can be opened")
    if parts.username or parts.password:
        raise IntakeRejected("links with embedded credentials are refused")
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not host or port not in (80, 443):
        raise IntakeRejected("only standard web ports (80/443) are allowed")
    if not _domain_allowed(host):
        raise IntakeRejected(f"links to {host} are not allowed")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IntakeRejected(f"could not resolve {host}") from exc
    ips = {info[4][0] for info in infos}
    for ip in ips:
        addr = ipaddress.ip_address(ip.split("%")[0])
        if not addr.is_global or addr.is_multicast or (addr.version == 6 and addr.ipv4_mapped and not addr.ipv4_mapped.is_global):
            raise IntakeRejected(f"{host} points to a private or reserved address; refused")
    return parts.scheme, host, port, sorted(ips)[0]


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template", "svg") and self._skip:
            self._skip -= 1
        if tag in ("p", "br", "tr", "li", "h1", "h2", "h3", "div", "td"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch_link(url: str) -> FetchedLink:
    import httpx

    import time

    max_bytes = settings.link_max_mb * 1024 * 1024
    deadline = time.monotonic() + settings.link_timeout_s * 2   # audit L-06: httpx timeouts are per read, not per download
    current = url
    for _hop in range(4):
        scheme, host, port, ip = vet_url(current)
        parts = urlsplit(current)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        ip_host = f"[{ip}]" if ":" in ip else ip
        pinned = f"{scheme}://{ip_host}:{port}{path}"
        headers = {"Host": host if port in (80, 443) else f"{host}:{port}", "User-Agent": "BMTL-ScrapTrust-LinkReader/1.0",
                   "Accept": "*/*"}
        with httpx.Client(timeout=settings.link_timeout_s, follow_redirects=False, verify=True, trust_env=False) as client:
            with client.stream("GET", pinned, headers=headers, extensions={"sni_hostname": host}) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise IntakeRejected("redirect without a target")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise IntakeRejected(f"the link answered HTTP {resp.status_code}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise IntakeRejected(f"the linked file is larger than {settings.link_max_mb} MB")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    if time.monotonic() > deadline:
                        raise IntakeRejected("the link took too long to download")
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise IntakeRejected(f"the linked file is larger than {settings.link_max_mb} MB")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        name = PurePosixPath(urlsplit(current).path).name or host
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "link"
        if ctype in ("text/html", "application/xhtml+xml"):
            text = html_to_text(bytes(body).decode("utf-8", errors="replace"))
            return FetchedLink(current, f"{name}.txt" if not name.endswith(".txt") else name, "text/plain",
                               f"Source: {current}\n\n{text}".encode("utf-8"))
        if "." not in name:
            ext = {"application/pdf": ".pdf", "text/csv": ".csv", "application/json": ".json", "image/jpeg": ".jpg", "image/png": ".png",
                   "image/webp": ".webp", "text/plain": ".txt", "text/markdown": ".md"}.get(ctype, "")
            name += ext
        return FetchedLink(current, name, ctype, bytes(body))
    raise IntakeRejected("too many redirects")
