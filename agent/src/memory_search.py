"""Cross-session memory search utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple
import math
import re


@dataclass
class MemoryHit:
    """Search result for memory retrieval."""

    text: str
    score: float
    session_id: str
    step: int


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _term_counts(tokens: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _build_idf(docs: List[Dict[str, int]]) -> Dict[str, float]:
    df: Dict[str, int] = {}
    for doc in docs:
        for term in doc.keys():
            df[term] = df.get(term, 0) + 1
    total = max(len(docs), 1)
    idf: Dict[str, float] = {}
    for term, freq in df.items():
        idf[term] = math.log((total + 1) / (freq + 1)) + 1.0
    return idf


def _tfidf_vector(counts: Dict[str, int], idf: Dict[str, float]) -> Dict[str, float]:
    vec: Dict[str, float] = {}
    for term, count in counts.items():
        vec[term] = count * idf.get(term, 0.0)
    return vec


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for term, value in a.items():
        norm_a += value * value
        if term in b:
            dot += value * b[term]
    for value in b.values():
        norm_b += value * value
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def rank_memories(
    query: str,
    docs: List[Tuple[str, str, int]],
    top_k: int,
    threshold: float,
) -> List[MemoryHit]:
    """Rank memory texts by cosine similarity."""
    tokenized_docs = [_term_counts(_tokenize(text)) for text, _, _ in docs]
    idf = _build_idf(tokenized_docs + [_term_counts(_tokenize(query))])
    doc_vecs = [_tfidf_vector(counts, idf) for counts in tokenized_docs]
    query_vec = _tfidf_vector(_term_counts(_tokenize(query)), idf)

    scored: List[MemoryHit] = []
    for (text, session_id, step), vec in zip(docs, doc_vecs):
        score = _cosine(query_vec, vec)
        if score >= threshold:
            scored.append(
                MemoryHit(text=text, score=score, session_id=session_id, step=step)
            )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]
