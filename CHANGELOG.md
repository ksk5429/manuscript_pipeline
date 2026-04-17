# Changelog

## 2026.04.2 (2026-04-17)

### Fixed
- CRITICAL: Removed text truncation in `_to_dict()` (was destroying manuscripts on save/load)
- CRITICAL: Filter unknown fields in StyleFlag/EvolvedSentence load (forward-compatible)
- Added `--resume` source file existence check
- Forward `--checkers` arg to checker subprocess
- Added timeout (120s) to `_run_checker` subprocess call

### Added
- Regression tests: full-text roundtrip, unknown-field tolerance
- 10 tests total

## 2026.04.1 (2026-04-17)

### Added
- Initial release: ManuscriptProtocol shared JSON format
- Pipeline orchestrator: check -> evolve -> render
- Threshold gate (blocks render if AI score exceeds limit)
- Offline and API evolution modes
- Markdown report generation
- 8 tests
