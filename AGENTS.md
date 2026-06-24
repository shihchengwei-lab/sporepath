# Agent Notes

- Keep the PoC dependency-free unless a dependency is clearly justified.
- Run `python -m unittest discover -s tests` before claiming code changes are done.
- Do not commit generated SQLite databases, generated graph HTML, private chat exports, or auth files.
- For new behavior, add focused unittest coverage first.
