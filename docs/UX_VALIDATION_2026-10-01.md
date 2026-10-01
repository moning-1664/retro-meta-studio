# UX regression validation — 2026-10-01

## Results

| Check | Result |
| --- | --- |
| Full Python suite (`tests`, before adding version tests) | 1,523 passed, 1 skipped, 1 xfailed; 42 subtests passed |
| New isolated version tests | 4 passed |
| Final full Playwright suite | 640 passed, no failures (3.5 minutes) |
| JavaScript/Python syntax and `git diff --check` | Passed |

Python command: `venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp .codex-test-tmp/full-final`.
Version command: same runner with `tests/test_version.py` and a separate temporary directory.
UI command: `node node_modules/@playwright/test/cli.js test --config=.codex-test-tmp/final.config.js --workers=4`.
The temporary UI configuration retains the repository's browser/test settings and uses a separately managed local static server on port 4180. The managed-server runner stalled during teardown in this environment; separating server lifetime allowed the final run to exit normally.

## Issues caught and corrected

- The scraper's apply guard blocked automatic search of the next game after successful application. Release the guard only after the apply job completes; the next search owns its own busy state. Multi-game auto advance and duplicate-apply prevention both pass.
- Grouped equal revisions could change the selected record merely by clicking the currently preferred card. Use the preferred record as that group's representative. The saved card remains selected and its apply button stays disabled until another card is selected.
- Settings assertions waited for any settings write, including independent session writes. They now wait for the specific value being verified.
- Existing selectors/expectations were updated for the shared candidate grid, localized labels, removed placeholder settings, compact header icon, Slate default and initial game selection. No-selection scenarios explicitly deselect the default game.

## Coverage added

- Initial selection and detail visibility without starting scraping.
- Single candidate auto selection; expansion preserves selection and footer visibility.
- An empty subsequent search cannot apply the previous candidate.
- Two-column expanded fields and scaled header/version alignment.
- Primary-button text/background contrast in all five themes (minimum ratio 4.5).
- Preferred/grouped revision selection.
- Patch/minor version increments, UI/source synchronization and malformed-version rejection using isolated files.

## Limits

UI tests use Chromium and the built-in API mock. Backend tests use synthetic fixtures. These results do not verify native WebView2 rendering, live ScreenScraper responses, NAS latency or physical MTP devices. Theme screenshots were generated; Slate was visually inspected. No package build, version bump, commit or push was performed.

Local detailed results are retained in ignored `.codex-test-tmp/backend-final.log`, `ui-verified.log`, `ui-complete-report.json` and `ui-visual-results/`.
