"""
Minimal, dependency-free PDF writer for library downloads (title + wrapped plain text, A4, multi-page).

Why no library: one more third-party package is one more supply-chain risk for a 50k-user rollout, and plain
text is all a library download needs. Uses the built-in Helvetica fonts (WinAnsi); characters outside
Windows-1252 are replaced with '?'.
"""
from __future__ import annotations

import textwrap
from typing import List

PAGE_W, PAGE_H = 595, 842          # A4 in points
MARGIN = 50
BODY_SIZE, TITLE_SIZE, LEADING = 10, 15, 13
WRAP = 98                          # characters per line at 10 pt Helvetica (conservative)


def _enc(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _lines(text: str) -> List[str]:
    out: List[str] = []
    for para in (text or "").replace("\r\n", "\n").replace("\t", "    ").split("\n"):
        wrapped = textwrap.wrap(para, WRAP, replace_whitespace=False, drop_whitespace=True, break_long_words=True) or [""]
        for line in wrapped:
            if line or (len(out) < 2 or out[-1] or out[-2]):   # at most two blank lines in a row
                out.append(line)
    return out


def write_text_pdf(title: str, body: str, subtitle: str = "") -> bytes:
    lines = _lines(body)
    per_page = int((PAGE_H - 2 * MARGIN - 40) / LEADING)
    pages = [lines[i:i + per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]

    objects: List[bytes] = []          # objects[i] is object number i+1

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_obj = add(b"")               # placeholder, filled once page ids are known
    page_ids = []
    for n, page in enumerate(pages, 1):
        y = PAGE_H - MARGIN
        ops = []
        if n == 1:
            ops.append(b"BT /F2 %d Tf %d %d Td (%s) Tj ET" % (TITLE_SIZE, MARGIN, y - TITLE_SIZE, _enc(title[:90])))
            y -= TITLE_SIZE + 8
            if subtitle:
                ops.append(b"BT /F1 8 Tf %d %d Td (%s) Tj ET" % (MARGIN, y - 8, _enc(subtitle[:140])))
                y -= 20
            y -= 6
        ops.append(b"BT /F1 %d Tf %d TL %d %d Td" % (BODY_SIZE, LEADING, MARGIN, y - BODY_SIZE))
        for i, line in enumerate(page):
            ops.append((b"(%s) Tj" if i == 0 else b"T* (%s) Tj") % _enc(line))
        ops.append(b"ET")
        ops.append(b"BT /F1 8 Tf %d %d Td (%s) Tj ET" % (PAGE_W - MARGIN - 60, MARGIN - 20, _enc(f"Page {n} of {len(pages)}")))
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                            % (pages_obj, PAGE_W, PAGE_H, font, bold, content)))
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % p for p in page_ids), len(page_ids))
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, xref)
    return bytes(out)
