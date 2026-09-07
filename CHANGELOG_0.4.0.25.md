# v0.4.0.25

- Keep Navigation's `+ Local` control; remove only the GameList top-right `+ Local` control.
- ES-DE canonical platform aliases for MasterDB: msx1→msx, famicom→nes, genesis/md→megadrive. sfc remains separate.
- Legacy MSX1 MasterDB entries are merged into MSX on load; other aliases are migrated when importing matching games.
- Alias merges preserve metadata versions and union media types.
- ES-DE CLEANUP system is excluded from scanning/system lists.
- Import from MasterDB now uses a background job with the existing progress UI and refreshes Local after completion.
- Added MasterDB Ctrl+C/Ctrl+V quick metadata+media overwrite for single-game cleanup.
- Replaced Unicode block-character system glyphs with SVG platform icons.
