"""Manuscript Pipeline Orchestrator.

Chains three engines in sequence:
  1. ai_style_checker  -- detect AI writing patterns
  2. sentence_evolver  -- rewrite flagged sentences
  3. publishing_engine -- render publication-quality DOCX

Each stage is optional. The protocol JSON tracks state between stages.

Usage:
    # Full pipeline
    python pipeline.py manuscript.qmd --check --evolve --render

    # Check only (generates protocol + report)
    python pipeline.py manuscript.qmd --check

    # Check + evolve (no render)
    python pipeline.py manuscript.qmd --check --evolve

    # Resume from existing protocol
    python pipeline.py --resume protocol.json --evolve --render

    # Set paths to engine repos
    python pipeline.py manuscript.qmd --check --evolve \\
        --checker-path /path/to/ai_style_checker \\
        --evolver-path /path/to/sentence_evolver \\
        --engine-path  /path/to/publishing_engine

    # Check with threshold gate (block render if AI score > 40)
    python pipeline.py manuscript.qmd --check --render --threshold 40
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from protocol import ManuscriptProtocol


def _find_engine(name: str, explicit_path: str | None = None) -> Path | None:
    """Locate an engine directory by searching common locations."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p

    # Search relative to this script, then parent, then siblings
    here = Path(__file__).parent
    candidates = [
        here.parent / name,                      # sibling directory
        here / name,                              # subdirectory
        Path.home() / name,                       # home directory
        Path(os.environ.get("ENGINES_DIR", "")) / name,  # env var
    ]
    for c in candidates:
        if c.exists() and (c / "cli.py").exists():
            return c
    return None


def _run_checker(
    qmd_path: Path,
    checker_path: Path,
    threshold: float | None = None,
) -> dict:
    """Run ai_style_checker and return JSON output."""
    cmd = [
        sys.executable,
        str(checker_path / "cli.py"),
        str(qmd_path),
        "--format", "json",
    ]
    if threshold is not None:
        cmd.extend(["--threshold", str(threshold)])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(checker_path),
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    if result.returncode != 0 and threshold is not None:
        print(f"  [GATE] AI score exceeded threshold {threshold}", file=sys.stderr)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  [ERROR] Checker output not valid JSON", file=sys.stderr)
        print(f"  stdout: {result.stdout[:200]}", file=sys.stderr)
        print(f"  stderr: {result.stderr[:200]}", file=sys.stderr)
        return {}


def _run_evolver_offline(
    flagged_sentences: list[tuple[str, list[str]]],
    evolver_path: Path,
) -> list[dict]:
    """Run sentence_evolver in offline mode on flagged sentences."""
    results = []
    for sentence, flags in flagged_sentences:
        cmd = [
            sys.executable,
            str(evolver_path / "cli.py"),
            sentence,
            "--offline",
            "--format", "json",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(evolver_path),
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        try:
            parsed = json.loads(result.stdout)
            if parsed:
                # Add flags to the result
                for entry in parsed:
                    entry["issue_flags"] = flags
                results.extend(parsed)
        except json.JSONDecodeError:
            pass
    return results


def _run_evolver_api(
    flagged_sentences: list[tuple[str, list[str]]],
    evolver_path: Path,
    personas: str | None = None,
    no_delphi: bool = False,
    model: str = "claude-sonnet-4-20250514",
    max_sentences: int = 10,
) -> list[dict]:
    """Run sentence_evolver with Claude API on flagged sentences."""
    # Write flagged sentences to a temp JSON for --from-checker format
    checker_json = {
        "results": [{
            "checker": "pipeline",
            "issues": [
                {
                    "severity": "warning",
                    "line": 0,
                    "message": flags[0] if flags else "",
                    "context": sentence,
                }
                for sentence, flags in flagged_sentences[:max_sentences]
            ],
        }]
    }

    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(checker_json, f)
        temp_path = f.name

    try:
        cmd = [
            sys.executable,
            str(evolver_path / "cli.py"),
            "--from-checker", temp_path,
            "--format", "json",
            "--model", model,
        ]
        if personas:
            cmd.extend(["--personas", personas])
        if no_delphi:
            cmd.append("--no-delphi")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(evolver_path),
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=300,
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"  [ERROR] Evolver output not valid JSON", file=sys.stderr)
            return []
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _run_renderer(
    qmd_path: Path,
    engine_path: Path,
    protocol: ManuscriptProtocol,
) -> list[str]:
    """Run publishing_engine to render DOCX files."""
    # The publishing_engine expects a paper directory, not a single file.
    # We pass the parent directory of the .qmd file.
    paper_dir = qmd_path.parent

    cmd = [
        sys.executable,
        str(engine_path / "engine" / "render_paper.py"),
        str(paper_dir),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(engine_path),
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=120,
    )

    if result.returncode != 0:
        print(f"  [ERROR] Renderer failed:", file=sys.stderr)
        print(f"  {result.stderr[:300]}", file=sys.stderr)
        return []

    # Find generated DOCX files
    output_dir = paper_dir / "_output"
    if output_dir.exists():
        return [str(f) for f in output_dir.glob("*.docx")]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="manuscript_pipeline",
        description="Orchestrate ai_style_checker + sentence_evolver + publishing_engine",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=str,
        help="Path to manuscript.qmd file",
    )

    # Stage flags
    parser.add_argument("--check", action="store_true", help="Run ai_style_checker")
    parser.add_argument("--evolve", action="store_true", help="Run sentence_evolver")
    parser.add_argument("--render", action="store_true", help="Run publishing_engine")

    # Resume from protocol
    parser.add_argument("--resume", type=str, help="Resume from existing protocol JSON")

    # Engine paths
    parser.add_argument("--checker-path", type=str, help="Path to ai_style_checker repo")
    parser.add_argument("--evolver-path", type=str, help="Path to sentence_evolver repo")
    parser.add_argument("--engine-path", type=str, help="Path to publishing_engine repo")

    # Check options
    parser.add_argument("--threshold", type=float, help="Block render if AI score exceeds this")
    parser.add_argument("--checkers", type=str, help="Comma-separated checker names")

    # Evolve options
    parser.add_argument("--offline", action="store_true", help="Use offline evolver (no API)")
    parser.add_argument("--personas", type=str, help="Comma-separated persona names")
    parser.add_argument("--no-delphi", action="store_true", help="Skip Delphi round")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514")
    parser.add_argument("--max-sentences", type=int, default=10)
    parser.add_argument("--min-severity", type=str, default="warning",
                        choices=["info", "warning", "error", "critical"])

    # Output
    parser.add_argument("-o", "--output", type=str, help="Protocol output path")
    parser.add_argument("--report", type=str, help="Markdown report output path")

    args = parser.parse_args()

    # ── Load or create protocol ───────────────────────────────────
    if args.resume:
        proto = ManuscriptProtocol.load(args.resume)
        qmd_path = Path(proto.source_path)
        print(f"Resumed protocol: {proto.summary()}")
    elif args.input:
        qmd_path = Path(args.input)
        if not qmd_path.exists():
            print(f"File not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        proto = ManuscriptProtocol.from_qmd(qmd_path)
        print(f"Created protocol from: {qmd_path.name}")
    else:
        parser.print_help()
        sys.exit(1)

    if not any([args.check, args.evolve, args.render]):
        print("\nNo stages specified. Use --check, --evolve, and/or --render.")
        sys.exit(1)

    # ── Stage 1: Check ────────────────────────────────────────────
    if args.check:
        checker_path = _find_engine("ai_style_checker", args.checker_path)
        if not checker_path:
            print("  [ERROR] ai_style_checker not found. Use --checker-path", file=sys.stderr)
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  STAGE 1: AI Style Check")
        print(f"{'='*60}")

        checker_output = _run_checker(qmd_path, checker_path, args.threshold)
        if checker_output:
            proto.add_style_check(checker_output)
            ai_score = proto.ai_score
            n_flags = len(proto.style_flags)
            print(f"  Score: {ai_score}/100 -- {proto.ai_label}")
            print(f"  Flags: {n_flags} total")

            # Count by severity
            sev_counts: dict[str, int] = {}
            for f in proto.style_flags:
                sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
            for sev in ["critical", "error", "warning", "info"]:
                if sev in sev_counts:
                    print(f"    [{sev.upper()}]: {sev_counts[sev]}")

            # Threshold gate
            if args.threshold and ai_score > args.threshold:
                print(f"\n  BLOCKED: AI score {ai_score} exceeds threshold {args.threshold}")
                print(f"  Run --evolve to fix flagged sentences before rendering.")
                if not args.evolve:
                    proto.save(args.output or "manuscript_protocol.json")
                    sys.exit(1)
        else:
            print("  [WARN] No checker output received")

    # ── Stage 2: Evolve ───────────────────────────────────────────
    if args.evolve:
        evolver_path = _find_engine("sentence_evolver", args.evolver_path)
        if not evolver_path:
            print("  [ERROR] sentence_evolver not found. Use --evolver-path", file=sys.stderr)
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  STAGE 2: Sentence Evolution")
        print(f"{'='*60}")

        flagged = proto.get_flagged_sentences(min_severity=args.min_severity)
        print(f"  Flagged sentences: {len(flagged)}")

        if flagged:
            if args.offline:
                print(f"  Mode: offline (rule-based)")
                evolver_output = _run_evolver_offline(flagged, evolver_path)
            else:
                print(f"  Mode: API ({args.model})")
                print(f"  Personas: {args.personas or 'all 10'}")
                print(f"  Delphi: {'disabled' if args.no_delphi else 'enabled'}")
                evolver_output = _run_evolver_api(
                    flagged, evolver_path,
                    personas=args.personas,
                    no_delphi=args.no_delphi,
                    model=args.model,
                    max_sentences=args.max_sentences,
                )

            if evolver_output:
                proto.add_evolution(evolver_output)
                n_evolved = len(proto.evolved_sentences)
                changed = sum(1 for e in proto.evolved_sentences if e.original != e.evolved)
                print(f"  Evolved: {n_evolved} sentences ({changed} changed)")
            else:
                print("  [WARN] No evolver output received")
        else:
            print("  No sentences to evolve (no flags at minimum severity)")

    # ── Stage 3: Render ───────────────────────────────────────────
    if args.render:
        engine_path = _find_engine("publishing_engine", args.engine_path)
        if not engine_path:
            print("  [ERROR] publishing_engine not found. Use --engine-path", file=sys.stderr)
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"  STAGE 3: DOCX Rendering")
        print(f"{'='*60}")

        outputs = _run_renderer(qmd_path, engine_path, proto)
        proto.render_outputs = outputs
        if "render" not in proto.stages_completed:
            proto.stages_completed.append("render")

        if outputs:
            print(f"  Generated {len(outputs)} DOCX files:")
            for out in outputs:
                print(f"    {Path(out).name}")
        else:
            print("  [WARN] No DOCX files generated")

    # ── Save protocol ─────────────────────────────────────────────
    output_path = args.output or "manuscript_protocol.json"
    proto.save(output_path)
    print(f"\n{'='*60}")
    print(f"  {proto.summary()}")
    print(f"  Protocol saved: {output_path}")
    print(f"{'='*60}\n")

    # ── Generate report ───────────────────────────────────────────
    if args.report:
        _generate_report(proto, args.report)
        print(f"  Report saved: {args.report}")


def _generate_report(proto: ManuscriptProtocol, path: str) -> None:
    """Generate a Markdown pipeline report."""
    lines = [
        f"# Manuscript Pipeline Report",
        f"",
        f"**Source:** `{proto.source_path}`",
        f"**Date:** {proto.created_at}",
        f"**Stages:** {' > '.join(proto.stages_completed)}",
        f"",
    ]

    if "check" in proto.stages_completed:
        lines.extend([
            f"## AI Style Check",
            f"",
            f"**Score:** {proto.ai_score}/100 -- {proto.ai_label}",
            f"**Total flags:** {len(proto.style_flags)}",
            f"",
        ])
        if proto.ai_score_breakdown:
            lines.append("| Checker | Contribution |")
            lines.append("|---------|-------------|")
            for checker, contrib in sorted(proto.ai_score_breakdown.items(), key=lambda x: -x[1]):
                lines.append(f"| {checker} | {contrib:.1f} |")
            lines.append("")

        # Top issues
        severe = [f for f in proto.style_flags if f.severity in ("error", "critical")]
        if severe:
            lines.append("### Critical/Error Issues")
            lines.append("")
            for flag in severe[:20]:
                lines.append(f"- **{flag.severity.upper()}** L{flag.line}: {flag.message}")
                if flag.suggestion:
                    lines.append(f"  - {flag.suggestion}")
            lines.append("")

    if "evolve" in proto.stages_completed:
        lines.extend([
            f"## Sentence Evolution",
            f"",
            f"**Evolved:** {len(proto.evolved_sentences)} sentences",
            f"",
        ])
        for i, es in enumerate(proto.evolved_sentences):
            lines.append(f"### Sentence {i + 1}")
            lines.append(f"- **Original:** {es.original}")
            lines.append(f"- **Evolved:** {es.evolved}")
            if es.flags:
                lines.append(f"- **Flags:** {', '.join(es.flags[:3])}")
            lines.append("")

    if proto.render_outputs:
        lines.extend([
            f"## Render Outputs",
            f"",
        ])
        for out in proto.render_outputs:
            lines.append(f"- `{Path(out).name}`")
        lines.append("")

    Path(path).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
