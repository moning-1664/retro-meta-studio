# UX simplification — 2026-10-01

## Implemented

- Empty Collection view explains the managed folders and offers a direct folder-open action.
- Collection round trips retain the Detail tab as well as selection and scroll.
- Collection detection checks at most two additional folder levels and 50 folders. It selects a nested root only when detection is unambiguous and complete.
- Existing ES-DE ROMDirectory settings supply the ROM folder only when it exists and the user has not entered another folder.
- Target is visible directly. Detection messages are short, with evidence in the tooltip.
- MTP uses the application's folder panel, standard actions, breadcrumb and selected path. Old browse responses cannot overwrite a newer location.
- Convert offers only a new destination folder; the existing-Collection branch is removed.
- Archive settings describe a metadata folder and the DB stored beneath it.
- Metadata import sources appear in the row-menu submenu.
- Paste runs directly; its arrow opens Fill and Replace. Unavailable row commands are hidden. Rename follows Favorite. Operation history is removed from the row menu, while recovery and Undo/Redo records remain intact.
- Filling empty fields does not require conflict approval. Existing field changes, media replacement and ROM replacement still do.
- Conflict previews are narrower, use fixed portrait/landscape previews, expose detailed fields and screenshots, and accept double-click choices.
- Revision previews expose all fields and screenshots, omit collection-internal source IDs and dates, and look for the cover in every record in a grouped revision.
- Scraper setup has a connection test. Applying locks the context; duplicate backend requests reuse the running job. The applied game's position is located after sorting changes.
- Metadata-only matches require title or filename resemblance in addition to developer/date evidence. A regression covers 1942 versus SonSon.
- Thumbnails preserve transparency; decoding failures are logged.
- Closing with unfinished jobs or unsaved Detail edits asks for confirmation. Native close requests enter the same flow. Shutdown removes incomplete scraper downloads after workers stop and preserves recovery backups.

## Validation and limits

- Full backend run: 1,452 passed, 1 skipped, 1 xfailed, 42 subtests passed (274.41 seconds).
- Full UI rerun after updating obsolete menu assertions: 621 passed (3.3 minutes).
- Additional native-close/transparent-thumbnail regression run: 15 passed, including both newly added cases.
- Final nested Archive detection and input-lock/Detail restoration UI run: 3 passed.
- JavaScript syntax and Git whitespace checks passed.

Automated backend and browser tests cover the above contracts. Browser tests use the bridge mock; actual MTP hardware, Windows native close events, NAS paths and remote ScreenScraper responses need device verification. In particular, the thumbnail changes do not establish the cause of every previously reported black image.

ROM folder inference currently supports known ES-DE settings. Unknown or inaccessible paths remain for manual selection. Nested-folder detection does not recursively scan the entire storage device.

## Metadata families

- PC88/PC9801, MSX/MSX2/MSX2+/Turbo R, Arcade/MAME/FBA/FBNeo/CPS, and PC Engine/CD/SuperGrafx reuse metadata. PC-FX remains separate.
- Candidate discovery uses the exact system first and searches related systems only when no candidate exists. Related-system candidates require manual selection.
- Cross-system paste updates metadata/media on existing games only; explicit single-game targets may have different filenames. Bulk targets require identical full filenames. ROM copying and cutting across systems are rejected.
- Collection add labels the first folder FrontEnd. Scraper connection results remain visible in the footer. Revision double-click selects the highlighted revision.
- Targeted backend validation: 206 passed and 19 subtests passed; additional real Collection MSX-to-MSX2 paste regression passed, preserving target ROM bytes. UI changes received JavaScript syntax validation; the earlier full UI run predates these final changes.
