# Manuscript Pipeline

Orchestrator for the five-engine academic manuscript toolkit. Chains detection, evolution, and rendering into a single command with shared protocol.

```
manuscript.qmd
     |
     v
 ┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
 │ ai_style_checker │ --> │ sentence_evolver  │ --> │ publishing_engine │
 │  12 checkers     │     │  10 personas      │     │  7 DOCX types     │
 │  score 0-100     │     │  A/B validation   │     │  --validate hook  │
 └─────────────────┘     └──────────────────┘     └───────────────────┘
         |                        |                        |
         v                        v                        v
   AI score + flags        Evolved sentences        Publication DOCX
```

## Quick Start

```bash
# Clone all repos as siblings
git clone https://github.com/ksk5429/manuscript_pipeline
git clone https://github.com/ksk5429/ai_style_checker
git clone https://github.com/ksk5429/sentence_evolver
git clone https://github.com/ksk5429/publishing_engine

# Full pipeline (check + evolve offline + render)
python pipeline.py manuscript.qmd --check --evolve --offline --render

# Check only (generates protocol + report)
python pipeline.py manuscript.qmd --check --report report.md

# Check with threshold gate (blocks render if AI score > 30)
python pipeline.py manuscript.qmd --check --render --threshold 30

# Check + evolve with Claude API (10 writer personas)
export ANTHROPIC_API_KEY=sk-ant-...
python pipeline.py manuscript.qmd --check --evolve

# Resume from saved protocol
python pipeline.py --resume manuscript_protocol.json --evolve --render

# Specify engine paths explicitly
python pipeline.py manuscript.qmd --check --evolve \
    --checker-path /path/to/ai_style_checker \
    --evolver-path /path/to/sentence_evolver \
    --engine-path  /path/to/publishing_engine
```

## The Protocol

All engines communicate through `ManuscriptProtocol` -- a shared JSON envelope:

```json
{
  "source_path": "manuscript.qmd",
  "ai_score": 20.6,
  "ai_label": "Mostly human, minor AI patterns",
  "style_flags": [...],
  "evolved_sentences": [...],
  "render_outputs": [...],
  "stages_completed": ["check", "evolve", "render"]
}
```

Features:
- **Resume from any stage** -- save protocol, review, continue later
- **Human review between stages** -- accept/reject evolved sentences before rendering
- **Forward-compatible** -- unknown fields in JSON are gracefully ignored
- **Full text preserved** -- no truncation in save/load roundtrip

## Pipeline Stages

### Stage 1: Check (`--check`)
Runs [ai_style_checker](https://github.com/ksk5429/ai_style_checker) with 12 checkers. Produces AI likelihood score (0-100), flags issues by severity, and forwards `--checkers` filter to the subprocess.

### Stage 2: Evolve (`--evolve`)
Runs [sentence_evolver](https://github.com/ksk5429/sentence_evolver) on flagged sentences (WARNING+ severity). Two modes:
- `--offline`: Rule-based transforms (no API, instant, free)
- Default: Claude API with 10 writer personas + Delphi consensus + A/B validation

### Stage 3: Render (`--render`)
Runs [publishing_engine](https://github.com/ksk5429/publishing_engine) to generate publication-quality DOCX files (7 document types).

## Pre-render Validation Hook

The publishing_engine has built-in ai_style_checker integration:

```bash
# In publishing_engine directory
python engine/render_paper.py paperB --validate
python engine/render_paper.py paperB --validate --threshold 30
python engine/render_paper.py --all --validate --threshold 30
```

## Architecture

```
manuscript_pipeline/
├── pipeline.py         # CLI orchestrator (3-stage subprocess chaining)
├── protocol.py         # ManuscriptProtocol (shared JSON format)
├── tests/
│   └── test_protocol.py  # 10 tests (roundtrip, unknown fields, etc.)
└── pyproject.toml
```

## Ecosystem

| Repo | Purpose | Standalone? |
|------|---------|-------------|
| [ai_style_checker](https://github.com/ksk5429/ai_style_checker) | 12-checker AI detection + fingerprinting | Yes |
| [sentence_evolver](https://github.com/ksk5429/sentence_evolver) | 10-persona sentence rewriting + A/B scoring | Yes |
| [publishing_engine](https://github.com/ksk5429/publishing_engine) | .qmd to 7 DOCX types + validation hook | Yes |
| **manuscript_pipeline** | Orchestrator (this repo) | Needs the others |
| [pdf_search_engine](https://github.com/ksk5429/pdf_search_engine) | Academic PDF discovery + markdown conversion | Yes |

## License

Apache 2.0
