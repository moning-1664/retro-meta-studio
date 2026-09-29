# RetroMeta Studio

Retro game ROM, metadata, media, and frontend collection management workspace for Windows.

**Platform scope:** RetroMeta Studio is a Windows desktop application. Linux and macOS builds are not planned. Frontend files or ROM storage used by other operating systems can be managed from Windows when the storage is accessible; that does not mean the application runs on those systems.

RetroMeta Studio is designed around a practical problem: the same ROM collection may need to be maintained in several frontend formats, while metadata, media, ROM locations, and storage devices change independently.

Instead of treating one frontend format as the application's database, RetroMeta Studio provides a workspace for:

- registering and scanning ROM collections
- reading and writing frontend-specific metadata
- matching equivalent games across collections
- comparing two collections
- collecting and resolving metadata through Archive
- preparing file changes as Plans before applying them
- copying, moving, deleting, and pasting files through a controlled file-operation layer
- converting metadata between supported frontend formats
- working with local, UNC, and device-backed storage
- launching games through RetroArch
- maintaining media and title data

The project started from [RetroGameManager](https://github.com/moning-1664/RetroGameManager), but the current architecture has been substantially redesigned as RetroMeta Studio.

> **Current version: 0.4.1.6**

## Project direction

The central idea is to separate **game collection data**, **frontend representation**, **comparison/matching**, and **file operations** instead of making a single frontend database responsible for everything.

The important concepts are:

| Concept | Role |
|---|---|
| **Collection** | A logical ROM/frontend library registered in the application |
| **Archive** | An optional library with revision history; appears after its folder is configured in Settings |
| **Compare** | Side-by-side analysis of two collections, including matches and differences |
| **Match** | Identification of equivalent games across collections |
| **Plan** | A calculated set of file changes that can be reviewed before Apply |
| **Adapter** | Frontend-specific reader/writer and format conversion layer |
| **Storage** | Abstraction for where ROMs and media physically reside |

The architecture is intentionally not tied to one frontend. ES-DE is an important target, but it is not the application's master format.

## Main workflow

A typical workflow is:

1. Register a Collection and its storage/system locations.
2. Scan the filesystem and build/update the Collection cache.
3. Read frontend metadata and media through the appropriate Adapter.
4. Review games and metadata in the web UI.
5. Use Match when the same game appears under different names.
6. Use Compare to inspect two collections side by side.
7. Optionally configure an Archive folder in Settings to keep selected games and their revision history.
8. Build a Plan for copy, paste, move, delete, Collection import, or Archive transfer.
9. Review the Plan.
10. Apply the Plan; file operations and Archive revision writes run in their respective handlers.
11. Export/write the result through the target Frontend Adapter.

## Supported Frontends

Frontend-specific processing is implemented in `adapters/`.

Current adapters include:

- ES-DE
- Pegasus
- LaunchBox
- EmulationStation

The adapter layer is responsible for reading/writing frontend-specific structures rather than forcing the rest of the application to understand every frontend's XML/JSON conventions.

ES-DE also has dedicated template support under:

```
adapters/esde_templates/
```

### ES-DE custom systems

ES-DE custom-system generation is supported through the ES-DE adapter.

The implementation distinguishes between normal system paths and cases where a system uses an explicitly configured/custom ROM location, including external storage and paths outside the normal ROM root.

## Collection

A Collection represents a usable frontend/game library rather than simply a directory.

Collection-related data includes:

- frontend type
- systems
- ROM locations
- metadata
- media references
- storage assignment
- scan/cache state

A Collection can therefore represent a local frontend installation, a separate ROM library, or another supported storage arrangement.

The application does not assume that all collections use the same filesystem layout.

## Metadata

Metadata is handled separately from the physical ROM files.

Depending on the frontend, metadata can include fields such as:

- title
- description
- genre
- developer
- publisher
- release date
- region
- players
- rating
- platform/system-specific fields

The application can read metadata from supported frontend formats, display it in the UI, compare it, and write it back through the appropriate adapter.

## Media

Media is treated as a separate part of collection management.

Supported media can include frontend-dependent assets such as:

- covers
- screenshots
- marquees
- mix images
- 3D boxes
- physical media
- videos
- other frontend-specific media

Media operations are integrated with Collection, Archive, Compare, Plan, and file-operation workflows.

Media cleanup functionality is also present in the application.

## Match

The Match system is intended for cases where two collections contain the same game but use different names or metadata.

The matching workflow includes:

1. exact matching
2. normalized-name matching
3. heuristic candidate matching
4. human confirmation

Matching is deliberately separate from simple filename comparison so that frontend naming differences do not automatically create duplicate game records.

## Compare

Compare provides a two-collection comparison view.

It can distinguish:

- Same
- Only in A
- Only in B
- Conflict

The UI provides side-by-side detail panels and a Gamelist for inspecting differences.

Compare is also connected to Plan so that selected changes can become planned file operations instead of immediately modifying files.

The Compare UI includes selection and navigation behaviors such as:

- single selection
- multi-selection
- Ctrl-click
- Shift selection
- Ctrl+A
- keyboard/arrow navigation
- swap
- refresh
- filtering
- conflict/difference filtering

## Archive

Archive is optional. Choose its folder in Settings; the app checks the folder structure and suggests a frontend format when it can identify one confidently. A Collection remains usable without an Archive. Archive keeps collected metadata, media, provenance, and revisions independently of the source Collection.

Archive currently supports concepts including:

- source tracking
- identity records
- revisions
- metadata comparison
- conflict detection
- Archive → Collection operations
- legacy Archive recovery/import
- Archive-side ROM/media discovery

Sending Collection entries to Archive and importing Archive entries into a Collection both enter Plan first. Apply performs the changes. Import can also use another open Collection as its source.

### Archive status

Archive is still an actively stabilized part of the project.

In particular, the following areas are under refinement:

- synchronization between Archive DB data and directory projections
- legacy media reconciliation
- refresh semantics for manually changed frontend files
- revision/conflict interaction
- durable media handling
- ROM identity matching

Therefore Archive should not currently be described as a completely finalized canonical master database.

## Plan and Apply

File changes are not required to happen immediately.

The Plan layer allows the application to calculate and review operations before they are applied.

Plan-related functionality includes:

- automatic plan generation
- capacity/size calculation
- copy
- move
- delete
- instance-to-instance operations
- paste
- Apply

Paste modes currently include:

| Mode | Purpose |
|---|---|
| **Patch** | Apply only the selected/required changes |
| **Overwrite** | Replace conflicting destination data |
| **Replace** | Replace the target set according to the planned operation |

This separation is important because metadata comparison and file mutation are different operations.

## File operation engine

Large Windows file operations are handled outside the main UI process.

The project supports:

### Robocopy

Robocopy is the primary Windows copy engine.

It is available through the application's file-operation layer and is the preferred engine for normal Windows file work.

### Native Worker

A separate native worker executable is also present:

```
native/MediaCopyWorker.exe
```

The worker can be used where configured, while Robocopy is preferred by the default `auto` configuration.

The relevant implementation includes:

```
native/
media_copy_worker.py
file_ops.py
```

## Storage

Physical storage is separated from application logic through the `storage/` layer.

The project supports local filesystem access and storage arrangements such as UNC paths, while the storage abstraction is also used for device-backed workflows.

This makes the application less dependent on a single drive letter or fixed ROM directory.

## MTP / Android

MTP support is implemented in the bridge/storage workflow for accessing Android devices.

The application can discover and browse MTP devices through the bridge layer.

This is intended for workflows such as managing ROM/media content on Android devices without treating the phone as a normal Windows drive.

MTP functionality is still being refined and should be considered an active development area rather than a completely frozen interface.

## RetroArch

The application includes RetroArch launch integration under:

```
app/launch/retroarch.py
```

This allows a Collection/game entry to be connected to an emulator launch workflow instead of treating the application purely as a metadata editor.

## Additional application functions

The current application also contains functionality for:

- Dashboard/statistics
- media cleanup
- title affix processing
- metadata conversion
- storage movement
- Windows window management
- multi-window/multi-instance workflows
- media server/bridge functionality
- background jobs

These functions are implemented in the current application architecture rather than being only planned concepts.

## GUI architecture

The user interface is a web UI running inside a Windows desktop shell.

Main pieces:

```
gui_web/       HTML / CSS / JavaScript UI
bridge/        Python ↔ Web UI bridge and jobs
pywebview      Desktop WebView shell
```

The UI uses a virtualized Gamelist for large collections and connects to the Python application through the bridge/API layer.

The application also contains Windows-specific window controls and management.

## Project structure

The current repository is organized roughly as follows:

```
retro-meta-studio/
├── adapters/          Frontend adapters
│   ├── base.py
│   ├── es_de.py
│   ├── pegasus.py
│   ├── launchbox.py
│   ├── emulationstation.py
│   └── esde_templates/
│
├── app/               Application/business logic
│   ├── archive/
│   ├── compare/
│   ├── convert/
│   ├── launch/
│   ├── match/
│   ├── metadata/
│   ├── model/
│   ├── plan/
│   ├── scan/
│   ├── store/
│   ├── dashboard.py
│   ├── media_cleanup.py
│   ├── paths.py
│   ├── storage_layout.py
│   └── title_affix.py
│
├── bridge/             Python ↔ Web UI bridge
│   ├── api.py
│   ├── jobs.py
│   ├── media_server.py
│   └── windows.py
│
├── storage/            Physical storage abstraction
├── importers/          Legacy/import parsing components
├── exporters/          Legacy/export writing components
├── gui_web/            HTML/CSS/JS frontend
├── native/             Native file-operation worker
├── tests/              Backend tests
├── tests_ui/           UI tests
├── tests_e2e/          Filesystem/E2E tests
├── main.py             Application entry point
├── requirements.txt
└── package.json
```

The older `importers/` and `exporters/` areas remain in the repository for compatibility/transition purposes; the current frontend architecture is centered on `adapters/`.

## Data storage

The application uses SQLite as its primary structured storage.

The current application data area is organized around:

```
db/
├── registry.db
├── archive.db
├── cache/
└── clipboard/
```

The exact contents of these databases are an implementation detail and may evolve as the architecture is stabilized.

The important separation is:

- Registry/application configuration
- Collection scan/cache data
- Archive data
- temporary/clipboard-related data

JSON/XML frontend files remain frontend representations rather than replacing SQLite as the application's internal structured storage.

## Testing

The repository contains several layers of tests.

### Backend

```bash
python -m unittest discover -s tests
```

### GUI

The web UI is tested with Playwright/Chromium.

```bash
npm install
npx playwright install chromium
npx playwright test
```

The UI can use a mock API when pywebview is unavailable, allowing many interaction tests to run without starting the complete desktop application.

### End-to-end / real filesystem

The repository also contains real-filesystem scenarios under `tests_e2e/`, including workflows for ROM-only entries and scoped operations.

These tests are important because many frontend/storage bugs cannot be detected by testing the UI against mock data alone.

### Frontend format validation

Frontend compatibility tests are used to verify adapter behavior against the target format rules.

The project does not assume that a successful internal round trip automatically proves that a frontend will interpret the generated files correctly. Where possible, generated test packs are used for practical validation.

## Requirements

Supported application platform and development tools:

- Windows 10/11
- Python 3.11+
- Node.js/npm for UI testing
- Chromium/Playwright for UI tests

The application runs on Windows only. File operations and device access use Windows facilities such as Robocopy, WebView2, and Windows filesystem/device APIs. Linux and macOS application support is outside the project scope.

## Development status

RetroMeta Studio is an active development project.

The core Collection/Scan/UI/Plan/Adapter/Match/Compare architecture is in place, while several areas continue to evolve:

- UI consistency across buttons, panels, dialogs, typography, and window controls
- Scraper match quality and result review
- Collection and Archive workflow clarity and reliability
- Archive synchronization and recovery behavior
- Archive revision/conflict UX
- Compare → Plan workflows
- ES-DE custom-system edge cases
- MTP/Android workflows
- media/file-operation edge cases
- frontend compatibility validation

The README intentionally describes these areas as they exist in the codebase rather than presenting future architectural goals as completed functionality.

## Design principles

### Frontend-neutral internal model

The application should not become an ES-DE-specific database with other frontend exporters attached afterward.

Frontend formats are representations of a collection.

### Separate information from mutation

Reading metadata, deciding what should change, and actually changing files are separate concerns.

That is why Match, Compare, Plan, and Apply are separate layers.

### Prefer reversible/inspectable operations

Where practical, file changes should be represented as operations that can be inspected before execution.

### Filesystem reality matters

The application is intended to work with real ROM libraries, large media sets, external storage, and Android devices. File paths and physical storage are therefore first-class concerns.

### Avoid hidden frontend assumptions

A ROM directory name, media filename, frontend XML field, or platform identifier should not silently become the application's universal identity rule.

## Running

From the project directory:

```bash
python main.py
```

For UI development/testing:

```bash
npm install
npx playwright install chromium
npx playwright test
```

## Repository

[moning-1664/retro-meta-studio](https://github.com/moning-1664/retro-meta-studio)

## Origin

RetroMeta Studio originated from the earlier RetroGameManager project, but the current project is a substantial architectural redesign rather than a simple continuation of the original frontend-management implementation.

## In one sentence

**RetroMeta Studio is a Windows desktop workspace for managing real retro-game collections, their ROMs, metadata, media, frontend formats, storage locations, comparisons, and planned file operations without making any single frontend the center of the system.**

## License

License information will be added when the project's distribution policy is finalized.
