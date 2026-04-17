"""Tests for ManuscriptProtocol and pipeline logic."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from protocol import ManuscriptProtocol, StyleFlag, EvolvedSentence


def test_from_text():
    proto = ManuscriptProtocol.from_text("Hello world.", source="test.md")
    assert proto.text == "Hello world."
    assert proto.source_path == "test.md"
    assert len(proto.source_hash) == 16


def test_add_style_check():
    proto = ManuscriptProtocol.from_text("Test text.")
    checker_json = {
        "ai_score": {"score": 45.5, "label": "Mixed signals", "breakdown": {"ai_patterns": 20}},
        "results": [
            {
                "checker": "ai_patterns",
                "metrics": {"density_per_1k_words": 15.0},
                "issues": [
                    {
                        "severity": "error",
                        "line": 5,
                        "message": "Filler phrase detected",
                        "match": "It is worth noting",
                        "context": "It is worth noting that X.",
                        "suggestion": "Remove filler",
                    }
                ],
            }
        ],
    }
    proto.add_style_check(checker_json)
    assert proto.ai_score == 45.5
    assert len(proto.style_flags) == 1
    assert proto.style_flags[0].severity == "error"
    assert "check" in proto.stages_completed


def test_add_evolution():
    proto = ManuscriptProtocol.from_text("Test text.")
    evolver_json = [
        {
            "original": "It is worth noting that X.",
            "evolved": "X.",
            "issue_flags": ["filler"],
            "round1": [{"persona": "compressor", "rewrite": "X.", "confidence": 0.9}],
            "round2": [],
            "aggregator_reasoning": "Removed filler.",
        }
    ]
    proto.add_evolution(evolver_json)
    assert len(proto.evolved_sentences) == 1
    assert proto.evolved_sentences[0].evolved == "X."
    assert "evolve" in proto.stages_completed


def test_get_evolved_text():
    proto = ManuscriptProtocol.from_text("It is worth noting that X is true. Also Y.")
    proto.evolved_sentences.append(EvolvedSentence(
        original="It is worth noting that X is true.",
        evolved="X is true.",
        applied=True,
    ))
    result = proto.get_evolved_text()
    assert result == "X is true. Also Y."


def test_accept_all():
    proto = ManuscriptProtocol.from_text("Test.")
    proto.evolved_sentences.append(EvolvedSentence(original="A", evolved="B"))
    proto.evolved_sentences.append(EvolvedSentence(original="C", evolved="D"))
    proto.accept_all_evolutions()
    assert all(e.applied for e in proto.evolved_sentences)


def test_get_flagged_sentences():
    proto = ManuscriptProtocol.from_text("Test.")
    proto.style_flags.append(StyleFlag(
        checker="ai_patterns", severity="error", line=1,
        message="Filler", context="It is worth noting that X.",
    ))
    proto.style_flags.append(StyleFlag(
        checker="ai_patterns", severity="info", line=2,
        message="Minor", context="Some other text.",
    ))
    flagged = proto.get_flagged_sentences(min_severity="warning")
    assert len(flagged) == 1
    assert flagged[0][0] == "It is worth noting that X."


def test_save_load_roundtrip():
    proto = ManuscriptProtocol.from_text("Test text for roundtrip.")
    proto.ai_score = 33.3
    proto.ai_label = "Mostly human"
    proto.style_flags.append(StyleFlag(
        checker="burstiness", severity="warning", line=0, message="Low CV",
    ))
    proto.evolved_sentences.append(EvolvedSentence(
        original="Old.", evolved="New.", applied=True,
    ))
    proto.stages_completed = ["check", "evolve"]

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        proto.save(f.name)
        loaded = ManuscriptProtocol.load(f.name)

    assert loaded.ai_score == 33.3
    assert len(loaded.style_flags) == 1
    assert len(loaded.evolved_sentences) == 1
    assert loaded.evolved_sentences[0].applied is True
    assert loaded.stages_completed == ["check", "evolve"]

    Path(f.name).unlink(missing_ok=True)


def test_save_load_preserves_full_text():
    """Regression test: text must survive roundtrip without truncation."""
    long_text = "This is a test sentence. " * 100  # ~2500 chars
    proto = ManuscriptProtocol.from_text(long_text)

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        proto.save(f.name)
        loaded = ManuscriptProtocol.load(f.name)

    assert loaded.text == long_text, "Text was truncated during save/load!"
    assert "..." not in loaded.text
    Path(f.name).unlink(missing_ok=True)


def test_load_ignores_unknown_fields():
    """Protocol should not crash when loading JSON with extra fields."""
    proto = ManuscriptProtocol.from_text("Test.")
    proto.style_flags.append(StyleFlag(
        checker="test", severity="info", line=1, message="test",
    ))
    proto.evolved_sentences.append(EvolvedSentence(
        original="A", evolved="B",
    ))

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        proto.save(f.name)
        # Inject unknown fields into the saved JSON
        data = json.loads(Path(f.name).read_text(encoding="utf-8"))
        data["style_flags"][0]["new_future_field"] = "value"
        data["evolved_sentences"][0]["another_new_field"] = 42
        Path(f.name).write_text(json.dumps(data), encoding="utf-8")

        # Should load without crashing
        loaded = ManuscriptProtocol.load(f.name)

    assert len(loaded.style_flags) == 1
    assert len(loaded.evolved_sentences) == 1
    Path(f.name).unlink(missing_ok=True)


def test_summary():
    proto = ManuscriptProtocol.from_text("Test.", source="paper.qmd")
    proto.ai_score = 22.0
    proto.stages_completed = ["check"]
    s = proto.summary()
    assert "22.0/100" in s
    assert "check" in s


# ── Runner ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        test_from_text,
        test_add_style_check,
        test_add_evolution,
        test_get_evolved_text,
        test_accept_all,
        test_get_flagged_sentences,
        test_save_load_roundtrip,
        test_save_load_preserves_full_text,
        test_load_ignores_unknown_fields,
        test_summary,
    ]

    passed = 0
    failed = 0
    for test in tests:
        name = test.__name__
        try:
            test()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    return failed == 0


if __name__ == "__main__":
    print("Running manuscript_pipeline tests...\n")
    success = run_all()
    sys.exit(0 if success else 1)
