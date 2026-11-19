"""
Store the Anthropic API key in app/backend/.env without showing it on screen or in any chat.

Usage:  venv/Scripts/python.exe scripts/set_anthropic_key.py
The key is typed (or pasted) at a hidden prompt, checked for the expected shape, and written as
ANTHROPIC_API_KEY=... replacing any existing (or commented-out) line. Nothing is printed back.
"""
from __future__ import annotations

import getpass
import re
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> None:
    print("Paste your Anthropic API key and press Enter (it stays hidden while you paste):")
    key = getpass.getpass("> ").strip().strip('"').strip("'")
    if not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]{20,}", key):
        print("That doesn't look like an Anthropic key (it should start with 'sk-ant-'). Nothing was changed.")
        return
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    out, done = [], False
    for line in lines:
        if re.match(r"^\s*#?\s*ANTHROPIC_API_KEY\s*=", line):
            if not done:
                out.append(f"ANTHROPIC_API_KEY={key}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"ANTHROPIC_API_KEY={key}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Saved (ending ...{key[-4:]}). Now restart ScrapTrust (close its window and run app/ScrapTrust.bat).")


if __name__ == "__main__":
    main()
