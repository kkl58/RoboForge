"""Skill library: verified skills are cached and reused.

This is what makes the system get better over time: the first time a task
is seen the LLM writes code; after verification the code is stored. Similar
future tasks are answered from the library with zero model calls.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_WORD = re.compile(r"[a-zA-Z\u4e00-\u9fff]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _keywords(text: str) -> set[str]:
    """Latin text → lowercase words; Chinese text → individual characters
    (Chinese has no spaces, so word-level matching never fires)."""
    words: set[str] = set()
    for w in _WORD.findall(text):
        if _CJK.search(w):
            words.update(w)
        else:
            words.add(w.lower())
    return words


class SkillLibrary:
    def __init__(self, path: str | Path = "skills/library.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skills: list[dict] = []
        if self.path.exists():
            self.skills = json.loads(self.path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    def find(self, task: str, min_overlap: int = 2) -> dict | None:
        """Return the best matching verified skill, or None."""
        want = _keywords(task)
        best, best_score = None, 0
        for skill in self.skills:
            if not skill.get("verified"):
                continue
            overlap = len(want & set(skill["keywords"]))
            if overlap > best_score:
                best, best_score = skill, overlap
        if best and best_score >= min_overlap:
            return best
        return None

    def save(self, task: str, code: str, verified: bool, source: str) -> dict:
        entry = {
            "id": f"skill_{len(self.skills) + 1:03d}",
            "task": task,
            "keywords": sorted(_keywords(task)),
            "code": code,
            "verified": verified,
            "source": source,          # "llm" or "mock" — provenance matters
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "uses": 0,
        }
        self.skills.append(entry)
        self._flush()
        return entry

    def record_use(self, skill_id: str) -> None:
        for skill in self.skills:
            if skill["id"] == skill_id:
                skill["uses"] += 1
                self._flush()
                return

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps(self.skills, ensure_ascii=False, indent=2), encoding="utf-8")
