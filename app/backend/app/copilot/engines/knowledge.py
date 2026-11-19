"""
Domain knowledge base + topic-scope check.

The knowledge base is a curated Markdown file (one "## " heading per entry)
shipped with the code. Retrieval is TF-IDF over title + body, so it needs no
model download and works offline. The same index decides whether a question
is within ScrapTrust's scope (scrap, waste, recycling, minerals, this project).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

DEFAULT_KB = Path(__file__).resolve().parents[1] / "knowledge" / "scrap_waste_minerals.md"

# Words that put a question inside the assistant's scope even when the KB has no close entry.
# Unambiguous domain words only; everyday words such as "lead", "glass", "rock", "car" or "grade"
# are left to the knowledge-base similarity score so "who will lead the team?" is not in scope.
DOMAIN_TERMS = re.compile(
    r"\b(scrap\w*|waste\w*|recycl\w*|ferrous|non-?ferrous|alumini?um|copper|brass|bronze|zinc|nickel|cobalt|"
    r"lithium|titanium|alloy\w*|stainless|batter(y|ies)|black mass|e-?waste|circuit boards?|pcbs?|plastics?|hdpe|"
    r"pvc|cullet|cardboard|compost\w*|light bulbs?|fluorescent|mercury|cfls?|automobile\w*|end-of-life vehicles?|"
    r"catalytic converters?|minerals?|mineralog\w*|geolog\w*|spectr\w*|absorption features?|reflectance|clays?|"
    r"kaolin\w*|muscovite|illite|carbonates?|calcite|dolomite|hematite|goethite|xrf|xrd|libs|assay\w*|smelt\w*|"
    r"contaminat\w*|hazardous|landfill\w*|dismantl\w*|shredd\w*|baler?s?|scraptrust|copilot|dinov2|k-?means|"
    r"ace green|asbestos|refrigerants?|radioactive|circular economy|metals?)\b",
    re.IGNORECASE,
)
SMALL_TALK = re.compile(
    r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|thanks?( you)?|thank you|ok(ay)?|cool|great|bye|"
    r"who are you|what are you|what can you do|help|how are you)\b[\s!.?]*$",
    re.IGNORECASE,
)

OFF_TOPIC_REPLY = (
    "Sorry, I couldn't match that to something I can help with. I'm the ScrapTrust assistant for **battery black mass, "
    "scrap, recycling and minerals**.\n\n"
    "You could try:\n"
    "- typing an XRF reading, for example *Ni 31.8 Co 9.1 Mn 9.5 Fe 0.4*\n"
    "- sending a photo of the XRF gun screen, or of scrap you want identified\n"
    "- asking *how should I store damaged lithium batteries?*\n"
    "- asking *what can you do?*"
)


@dataclass
class KBEntry:
    title: str
    text: str


class KnowledgeBase:
    def __init__(self, path: Path = DEFAULT_KB) -> None:
        self.path = Path(path)
        self.entries: List[KBEntry] = []
        self._vectorizer = None
        self._matrix = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._matrix is not None:
            return
        with self._lock:
            if self._matrix is not None:
                return
            from sklearn.feature_extraction.text import TfidfVectorizer

            raw = self.path.read_text(encoding="utf-8")
            entries = []
            for block in re.split(r"^## ", raw, flags=re.MULTILINE)[1:]:
                title, _, body = block.partition("\n")
                entries.append(KBEntry(title.strip(), " ".join(body.split())))
            self.entries = entries
            self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
            # Titles count twice: they name the topic precisely.
            self._matrix = self._vectorizer.fit_transform([f"{e.title} {e.title} {e.text}" for e in entries])

    def search(self, query: str, k: int = 3) -> List[dict]:
        self._load()
        if not query.strip():
            return []
        q = self._vectorizer.transform([query])
        scores = (self._matrix @ q.T).toarray().ravel()
        order = scores.argsort()[::-1][:k]
        return [
            {"title": self.entries[i].title, "text": self.entries[i].text, "score": round(float(scores[i]), 3)}
            for i in order
            if scores[i] > 0
        ]

    def best_score(self, query: str) -> float:
        hits = self.search(query, k=1)
        return hits[0]["score"] if hits else 0.0

    def shared_terms(self, query: str, entry_text: str) -> int:
        """Distinct content words of the query that also occur in an entry (single-word matches are weak)."""
        self._load()
        analyzer = self._vectorizer.build_analyzer()
        q_terms = {t for t in analyzer(query) if " " not in t}
        e_terms = {t for t in analyzer(entry_text) if " " not in t}
        return len(q_terms & e_terms)


def classify_scope(text: str, kb: Optional[KnowledgeBase] = None, threshold: float = 0.12) -> str:
    """'small_talk', 'in_scope' or 'off_topic' for a text-only question."""
    if SMALL_TALK.match(text or ""):
        return "small_talk"
    if DOMAIN_TERMS.search(text or ""):
        return "in_scope"
    if kb is not None:
        hits = kb.search(text, k=1)
        if hits and hits[0]["score"] >= threshold:
            top = hits[0]
            if kb.shared_terms(text, f"{top['title']} {top['text']}") >= 2:
                return "in_scope"
    return "off_topic"
