"""Manuscript Protocol -- shared JSON format for the three-engine pipeline.

The protocol defines a standard data envelope that flows between:
  1. ai_style_checker  -> produces style_flags
  2. sentence_evolver  -> consumes flags, produces evolved_sentences
  3. publishing_engine -> consumes evolved text, renders DOCX

This file is the single source of truth for the protocol format.
Each engine can import or vendor this file.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "0.1.0"


@dataclass
class StyleFlag:
    """A single issue flagged by ai_style_checker."""
    checker: str
    severity: str  # info, warning, error, critical
    line: int
    message: str
    match: str = ""
    context: str = ""
    suggestion: str = ""


@dataclass
class EvolvedSentence:
    """A sentence that was evolved by sentence_evolver."""
    original: str
    evolved: str
    flags: list[str] = field(default_factory=list)
    persona_contributions: dict[str, str] = field(default_factory=dict)
    reasoning: str = ""
    applied: bool = False


@dataclass
class ManuscriptProtocol:
    """Shared data envelope for the three-engine pipeline."""

    # Source
    source_path: str = ""
    source_hash: str = ""
    created_at: str = ""

    # Text content
    text: str = ""
    yaml_frontmatter: dict[str, Any] = field(default_factory=dict)

    # Stage 1: ai_style_checker
    ai_score: float = 0.0
    ai_label: str = ""
    ai_score_breakdown: dict[str, float] = field(default_factory=dict)
    style_flags: list[StyleFlag] = field(default_factory=list)
    checker_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Stage 2: sentence_evolver
    evolved_sentences: list[EvolvedSentence] = field(default_factory=list)
    evolution_metadata: dict[str, Any] = field(default_factory=dict)

    # Stage 3: publishing_engine
    render_config: dict[str, Any] = field(default_factory=dict)
    render_outputs: list[str] = field(default_factory=list)

    # Pipeline
    pipeline_version: str = PROTOCOL_VERSION
    stages_completed: list[str] = field(default_factory=list)

    @classmethod
    def from_qmd(cls, qmd_path: str | Path) -> ManuscriptProtocol:
        """Create from a .qmd manuscript file."""
        path = Path(qmd_path)
        raw = path.read_text(encoding="utf-8", errors="replace")

        yaml_data: dict[str, Any] = {}
        text = raw
        if raw.startswith("---"):
            end = raw.find("---", 3)
            if end != -1:
                try:
                    import yaml
                    yaml_data = yaml.safe_load(raw[3:end]) or {}
                except Exception:
                    pass
                text = raw[end + 3:].lstrip("\n")

        return cls(
            source_path=str(path.resolve()),
            source_hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
            created_at=datetime.now().isoformat(),
            text=text,
            yaml_frontmatter=yaml_data,
        )

    @classmethod
    def from_text(cls, text: str, source: str = "<stdin>") -> ManuscriptProtocol:
        return cls(
            source_path=source,
            source_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
            created_at=datetime.now().isoformat(),
            text=text,
        )

    def add_style_check(self, checker_json: dict[str, Any]) -> None:
        """Ingest ai_style_checker --format json output."""
        self.ai_score = checker_json.get("ai_score", {}).get("score", 0)
        self.ai_label = checker_json.get("ai_score", {}).get("label", "")
        self.ai_score_breakdown = checker_json.get("ai_score", {}).get("breakdown", {})

        for result in checker_json.get("results", []):
            checker_name = result.get("checker", "")
            self.checker_metrics[checker_name] = result.get("metrics", {})
            for issue in result.get("issues", []):
                self.style_flags.append(StyleFlag(
                    checker=checker_name,
                    severity=issue.get("severity", "info"),
                    line=issue.get("line", 0),
                    message=issue.get("message", ""),
                    match=issue.get("match", ""),
                    context=issue.get("context", ""),
                    suggestion=issue.get("suggestion", ""),
                ))

        if "check" not in self.stages_completed:
            self.stages_completed.append("check")

    def add_evolution(self, evolver_json: list[dict[str, Any]]) -> None:
        """Ingest sentence_evolver --format json output."""
        for entry in evolver_json:
            contributions = {}
            for rw in entry.get("round1", []) + entry.get("round2", []):
                contributions[rw["persona"]] = rw.get("rewrite", "")
            self.evolved_sentences.append(EvolvedSentence(
                original=entry.get("original", ""),
                evolved=entry.get("evolved", ""),
                flags=entry.get("issue_flags", []),
                persona_contributions=contributions,
                reasoning=entry.get("aggregator_reasoning", ""),
            ))

        if "evolve" not in self.stages_completed:
            self.stages_completed.append("evolve")

    def get_evolved_text(self) -> str:
        """Return text with accepted evolutions applied."""
        result = self.text
        for es in self.evolved_sentences:
            if es.applied and es.original in result:
                result = result.replace(es.original, es.evolved, 1)
        return result

    def accept_all_evolutions(self) -> None:
        for es in self.evolved_sentences:
            es.applied = True

    def get_flagged_sentences(self, min_severity: str = "warning") -> list[tuple[str, list[str]]]:
        """Get (context, [messages]) for feeding to sentence_evolver."""
        severity_order = {"info": 0, "warning": 1, "error": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 1)
        seen: dict[str, list[str]] = {}
        for flag in self.style_flags:
            if severity_order.get(flag.severity, 0) >= min_level and flag.context:
                seen.setdefault(flag.context, []).append(flag.message)
        return list(seen.items())

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self._to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> ManuscriptProtocol:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        proto = cls(
            source_path=data.get("source_path", ""),
            source_hash=data.get("source_hash", ""),
            created_at=data.get("created_at", ""),
            text=data.get("text", ""),
            yaml_frontmatter=data.get("yaml_frontmatter", {}),
            ai_score=data.get("ai_score", 0),
            ai_label=data.get("ai_label", ""),
            ai_score_breakdown=data.get("ai_score_breakdown", {}),
            checker_metrics=data.get("checker_metrics", {}),
            render_config=data.get("render_config", {}),
            render_outputs=data.get("render_outputs", []),
            pipeline_version=data.get("pipeline_version", PROTOCOL_VERSION),
            stages_completed=data.get("stages_completed", []),
        )
        for f in data.get("style_flags", []):
            proto.style_flags.append(StyleFlag(**f))
        for e in data.get("evolved_sentences", []):
            proto.evolved_sentences.append(EvolvedSentence(**e))
        proto.evolution_metadata = data.get("evolution_metadata", {})
        return proto

    def _to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "created_at": self.created_at,
            "text": self.text[:500] + "..." if len(self.text) > 500 else self.text,
            "yaml_frontmatter": self.yaml_frontmatter,
            "ai_score": self.ai_score,
            "ai_label": self.ai_label,
            "ai_score_breakdown": self.ai_score_breakdown,
            "style_flags": [asdict(f) for f in self.style_flags],
            "checker_metrics": self.checker_metrics,
            "evolved_sentences": [asdict(e) for e in self.evolved_sentences],
            "evolution_metadata": self.evolution_metadata,
            "render_config": self.render_config,
            "render_outputs": self.render_outputs,
            "pipeline_version": self.pipeline_version,
            "stages_completed": self.stages_completed,
        }

    def summary(self) -> str:
        stages = " > ".join(self.stages_completed) if self.stages_completed else "(none)"
        n_flags = len(self.style_flags)
        n_evolved = len(self.evolved_sentences)
        n_accepted = sum(1 for e in self.evolved_sentences if e.applied)
        return (
            f"Protocol: {Path(self.source_path).name} | "
            f"Score: {self.ai_score}/100 | "
            f"Flags: {n_flags} | "
            f"Evolved: {n_evolved} ({n_accepted} accepted) | "
            f"Stages: {stages}"
        )
