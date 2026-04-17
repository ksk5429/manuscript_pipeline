# Manuscript Pipeline

Orchestrator for the three-engine academic manuscript toolkit:

```
manuscript.qmd
     |
     v
 ┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
 │ ai_style_checker │ --> │ sentence_evolver  │ --> │ publishing_engine │
 │   (detect)       │     │   (evolve)        │     │   (render)        │
 └─────────────────┘     └──────────────────┘     └───────────────────┘
     |                        |                        |
     v                        v                        v
  AI score 0-100          Rewritten sentences       Publication DOCX
  89 issue flags          by 10 writer personas     7 document types
```

## Quick Start

```bash
# Clone all four repos as siblings
git clone https://github.com/ksk5429/manuscript_pipeline
git clone https://github.com/ksk5429/ai_style_checker
git clone https://github.com/ksk5429/sentence_evolver
git clone https://github.com/ksk5429/publishing_engine

# Full pipeline (check + evolve offline + render)
python pipeline.py manuscript.qmd --check --evolve --offline --render

# Check only
python pipeline.py manuscript.qmd --check

# Check + evolve with Claude API (10 writer personas + Delphi consensus)
export ANTHROPIC_API_KEY=sk-ant-...
python pipeline.py manuscript.qmd --check --evolve

# Check with threshold gate (blocks render if AI score > 40)
python pipeline.py manuscript.qmd --check --render --threshold 40

# Resume from saved protocol
python pipeline.py --resume manuscript_protocol.json --evolve --render

# Generate Markdown report
python pipeline.py manuscript.qmd --check --evolve --offline --report report.md

# Custom engine paths
python pipeline.py manuscript.qmd --check --evolve \
    --checker-path /path/to/ai_style_checker \
    --evolver-path /path/to/sentence_evolver \
    --engine-path  /path/to/publishing_engine
```

## The Protocol

All three engines communicate through a shared JSON format (`manuscript_protocol.json`):

```json
{
  "source_path": "manuscript.qmd",
  "ai_score": 58.8,
  "ai_label": "Mixed signals -- needs human review",
  "style_flags": [...],
  "evolved_sentences": [...],
  "render_outputs": [...],
  "stages_completed": ["check", "evolve", "render"]
}
```

Each engine reads its input section and writes its output section. The protocol file persists state between stages, enabling:
- Resume from any stage
- Human review between stages
- Selective acceptance of evolved sentences
- CI/CD integration with threshold gates

## Pre-render Validation Hook

The publishing_engine has built-in support for pre-render validation:

```bash
# In publishing_engine directory
python engine/render_paper.py paperB_buckingham_pi --validate

# Block render if AI score exceeds threshold
python engine/render_paper.py paperB_buckingham_pi --validate --threshold 40
```

This automatically runs ai_style_checker before rendering and saves the report to `_output/style_report.json`.

## Pipeline Stages

### Stage 1: Check (`--check`)
Runs [ai_style_checker](https://github.com/ksk5429/ai_style_checker) with 9 modular checkers. Produces an AI likelihood score (0-100) and flags issues by severity.

### Stage 2: Evolve (`--evolve`)
Runs [sentence_evolver](https://github.com/ksk5429/sentence_evolver) on flagged sentences. Two modes:
- `--offline`: Rule-based transforms (no API, instant)
- Default: Claude API with 10 writer personas + Delphi consensus

### Stage 3: Render (`--render`)
Runs [publishing_engine](https://github.com/ksk5429/publishing_engine) to generate publication-quality DOCX files.

## Architecture

```
manuscript_pipeline/
├── pipeline.py         # CLI orchestrator
├── protocol.py         # ManuscriptProtocol (shared JSON format)
├── tests/
│   └── test_protocol.py  # 8 tests for protocol logic
├── pyproject.toml
└── README.md
```

## Running Tests

```bash
python tests/test_protocol.py
```

## The Ecosystem

| Repo | Purpose | Standalone? |
|------|---------|-------------|
| [ai_style_checker](https://github.com/ksk5429/ai_style_checker) | Detect AI writing patterns | Yes |
| [sentence_evolver](https://github.com/ksk5429/sentence_evolver) | Multi-agent sentence rewriting | Yes |
| [publishing_engine](https://github.com/ksk5429/publishing_engine) | DOCX rendering for journals | Yes |
| **manuscript_pipeline** | Orchestrate all three | Needs the others |

Each engine is independently installable and usable. The pipeline adds orchestration and the shared protocol.

## License

Apache 2.0
