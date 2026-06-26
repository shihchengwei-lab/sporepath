from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


DEFAULT_DEDUPE_THRESHOLD = 0.92


@dataclass(frozen=True)
class FragmentDecision:
    keep: bool
    reason: str
    fingerprint: str


class FragmentFilter:
    def __init__(
        self,
        *,
        dedupe: bool = True,
        conservative: bool = True,
        threshold: float = DEFAULT_DEDUPE_THRESHOLD,
    ):
        self.dedupe = dedupe
        self.conservative = conservative
        self.threshold = threshold
        self._fingerprints: set[str] = set()
        self._token_sets: list[set[str]] = []

    def keep(self, text: str) -> FragmentDecision:
        fingerprint = fragment_fingerprint(text)
        if self.conservative and is_disposable_fragment(text):
            return FragmentDecision(False, "disposable-fragment", fingerprint)
        if self.dedupe and self._is_duplicate(text, fingerprint):
            return FragmentDecision(False, "near-duplicate", fingerprint)

        self._fingerprints.add(fingerprint)
        tokens = _token_set(text)
        if tokens:
            self._token_sets.append(tokens)
        return FragmentDecision(True, "keep", fingerprint)

    def _is_duplicate(self, text: str, fingerprint: str) -> bool:
        if fingerprint in self._fingerprints:
            return True
        tokens = _token_set(text)
        if not tokens:
            return False
        return any(_jaccard(tokens, seen) >= self.threshold for seen in self._token_sets)


def fragment_fingerprint(text: str) -> str:
    normalized = _normalize_for_dedupe(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def is_disposable_fragment(text: str) -> bool:
    folded = text.strip().casefold()
    if not folded:
        return True
    if _looks_like_command_xml(folded):
        return True
    if folded.startswith("/remote-control is active"):
        return True
    if _looks_like_shell_transcript(folded):
        return True
    if _looks_like_stale_recap(folded):
        return True
    return False


def _normalize_for_dedupe(text: str) -> str:
    folded = text.casefold()
    folded = folded.replace("(disable recaps in /config)", " ")
    folded = re.sub(r"https?://\S+", " ", folded)
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _token_set(text: str) -> set[str]:
    normalized = _normalize_for_dedupe(text)
    tokens = re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]+", normalized)
    return {token for token in tokens if len(token) >= 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _looks_like_command_xml(folded: str) -> bool:
    return (
        folded.startswith("<command-name")
        or folded.startswith("<command-message")
        or ("<command-name" in folded and "<command-args" in folded)
        or ("<command-message" in folded and "</command-message>" in folded)
    )


def _looks_like_shell_transcript(folded: str) -> bool:
    if re.search(r"^[\w.-]+@[\w.-]+:[^$#]+[$#]\s+", folded):
        return True
    return " cat > " in folded and " <<'eof'" in folded


def _looks_like_stale_recap(folded: str) -> bool:
    has_recap_marker = "disable recaps in /config" in folded
    if not has_recap_marker:
        return False
    return (
        folded.startswith("你要我")
        or folded.startswith("你在準備")
        or folded.startswith("你在准备")
        or (folded.startswith("在準備") and "下一步" in folded)
        or (folded.startswith("在准备") and "下一步" in folded)
        or ("結果是" in folded and "下一步等你決定" in folded)
        or ("result is" in folded and "next:" in folded and "waiting" in folded)
    )
