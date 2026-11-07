from __future__ import annotations

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

_FW = {i: i - 0xFEE0 for i in range(0xFF01, 0xFF5F)}
_FW.update({0x3000: 0x20})

_PUNCT = {
    "，": ",", "。": ".", "；": ";", "：": ":", "（": "(", "）": ")",
    "【": "[", "】": "]", "“": '"', "”": '"', "‘": "'", "’": "'",
    "？": "?", "！": "!", "、": ",", "－": "-", "—": "-", "…": "...",
    "～": "~", "《": "<", "》": ">",
}

_LEAD_NO = re.compile(r"^\s*(?:第?\s*\d+\s*[题、.．)）]|\d+[、.．])\s*")
_SPACE = re.compile(r"[\s\u00a0\u3000]+")
_UNDER = re.compile(r"[_＿]{2,}|_{1,}")

def normalize(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.translate(_FW)
    s = "".join(_PUNCT.get(ch, ch) for ch in s)
    s = _LEAD_NO.sub("", s)
    s = _UNDER.sub("_", s)
    s = _SPACE.sub("", s)
    return s.strip()

class Bank:
    def __init__(self, raw: dict[str, str]):

        self._map: dict[str, str] = {}
        self._raw: dict[str, str] = {}
        for q, a in raw.items():
            k = normalize(q)
            if not k:
                continue
            self._raw[q] = str(a)
            self._map.setdefault(k, q)
        self._keys = list(self._map.keys())

    def __len__(self) -> int:
        return len(self._map)

    @classmethod
    def from_js(cls, path: str) -> "Bank":
        with open(path, "r", encoding="utf-8-sig") as f:
            src = f.read()
        return cls.from_js_text(src)

    @classmethod
    def from_js_text(cls, src: str) -> "Bank":
        start = src.find("{", src.find("answers"))
        if start < 0:
            raise ValueError("answer.js 里找不到 answers 对象")
        depth = 0
        end = -1
        in_str = False
        esc = False
        for i in range(start, len(src)):
            ch = src[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end < 0:
            raise ValueError("answers 对象未闭合")
        body = src[start:end]
        body = re.sub(r",(\s*[}\]])", r"\1", body)
        raw = json.loads(body)
        return cls(raw)

    def exact(self, question: str) -> str | None:
        q = normalize(question)
        hit = self._map.get(q)
        return self._raw[hit] if hit else None

    def fuzzy(self, question: str, threshold: float = 0.86) -> tuple[str, float, str] | None:
        q = normalize(question)
        if not q:
            return None
        best = None
        best_score = 0.0
        for k in self._keys:

            if abs(len(k) - len(q)) > max(6, len(q) * 0.25):
                continue
            score = SequenceMatcher(None, q, k).ratio()
            if score > best_score:
                best_score, best = score, k
        if best is None or best_score < threshold:
            return None
        return self._raw[self._map[best]], best_score, self._map[best]

    def lookup(self, question: str) -> tuple[str | None, str, float]:
        a = self.exact(question)
        if a:
            return a, "exact", 1.0
        f = self.fuzzy(question)
        if f:
            return f[0], "fuzzy", f[1]
        return None, "miss", 0.0

def split_answer(answer: str) -> list[str]:
    if not answer:
        return []
    return [c for c in str(answer).upper() if c in "ABCDEFGH"]

class TextBank:

    def __init__(self, path: str, fallback: str | None = None):
        self.path = path
        self.data: dict[str, dict] = {}

        for p in (fallback, path):
            if not p or not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for item in json.load(f):
                        k = normalize(item.get("q") or "")
                        if k:
                            self.data[k] = item
            except Exception:
                continue

    def __len__(self) -> int:
        return len(self.data)

    def lookup(self, question: str) -> list[str] | None:
        item = self.data.get(normalize(question))
        if not item:
            return None
        texts = item.get("texts") or []
        return texts or None

    def add(self, question: str, texts: list[str]) -> None:
        k = normalize(question)
        if k:
            self.data[k] = {"q": question, "texts": texts}

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(self.data.values()), f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
