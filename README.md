# Sporepath

[繁體中文](README.zh-TW.md)

![A small Sporepath scout organizes AI chat fragments into focus paths and latent idea spores](assets/hero-mascot.png)

Local-first experiment for turning AI chat history into a living memory graph.

Sporepath grows the paths you use, and keeps forgotten thoughts ready to wake.
The goal is not another note archive. The experiment is whether old chat
fragments can become two useful layers:

- **Focus paths**: active, frequently touched ideas become thicker and easier to
  continue.
- **Latent paths**: quiet, low-activation ideas sink out of the way but can be
  resurfaced when a new problem creates a useful bridge.

Small local models are treated as scouts, not as the brain. They propose
candidate memory atoms. Local rules and later usage signals decide which paths
thicken, fade, or sink into archive.

## What It Does

- Imports ChatGPT-style `conversations.json` and generic JSONL chat logs.
- Extracts `thought atoms` with either:
  - a deterministic rules baseline, or
  - a local Ollama model such as `qwen3:1.7b`.
- Stores atoms and shared-tag edges in SQLite.
- Builds readable `digested notes` from atoms, so you can review old chats
  without opening the full conversation log.
- Exports digested notes to a local Obsidian-compatible Markdown vault.
- Tracks `activation`, a rough path-strength score.
- Produces a local interactive HTML graph.
- Uses `codex exec` only for optional inspiration bridging, so an existing
  ChatGPT/Codex subscription can be used instead of an API key.

## Install

```powershell
git clone https://github.com/shihchengwei-lab/sporepath.git
cd sporepath
python -m pip install -e .
```

Or run from the checkout without installing:

```powershell
$env:PYTHONPATH = "src"
python -m sporepath doctor
```

## Low-Friction Desktop Flow

On Windows, double-click:

```text
Sporepath.bat
```

This opens a small local window with three everyday actions:

- **Refresh Now**: rebuild notes, export the Obsidian vault, and refresh the graph.
- **Sync Vault**: treat edited Obsidian notes as usage feedback and thicken their source atoms.
- **Open Vault**: open the Markdown vault folder for Obsidian.
- **Inspire**: enter a stuck question and ask Codex for weird-but-bridged next moves.

The batch launcher uses `real_memory.sqlite` in this checkout by default. The
window still lets you edit the DB, chat export, vault, and graph paths before
running anything.

Use **Auto-detect Sources** to find local Codex and Claude conversation stores.
Sporepath only uses an allowlist of likely conversation sources:

```text
{home}/.codex/history.jsonl
{home}/.codex/sessions/
{home}/.codex/archived_sessions/
{home}/.claude/history.jsonl
{home}/.claude/projects/
{home}/.claude/sessions/
```

It deliberately ignores credentials, auth files, settings, logs, caches, and
other non-conversation files.

## Quick Start

Try the included sample first:

```powershell
$env:PYTHONPATH = "src"
python -m sporepath --db sample_memory.sqlite ingest examples\sample_chat.jsonl
python -m sporepath --db sample_memory.sqlite digest
python -m sporepath --db sample_memory.sqlite notes
python -m sporepath --db sample_memory.sqlite focus
python -m sporepath --db sample_memory.sqlite graph --out graph.html
```

Open `graph.html` in your browser.

## Import Your Own Chats

For a ChatGPT export saved in your Downloads folder:

```powershell
$chat = "$env:USERPROFILE\Downloads\conversations.json"
python -m sporepath --db my_memory.sqlite ingest $chat
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite notes
python -m sporepath --db my_memory.sqlite stats
python -m sporepath --db my_memory.sqlite focus
```

Use the local model extractor on a small slice first:

```powershell
ollama pull qwen3:1.7b
$chat = "$env:USERPROFILE\Downloads\chat.jsonl"
python -m sporepath --db qwen_trial.sqlite ingest $chat --extractor ollama --model qwen3:1.7b --max-turns 50
python -m sporepath --db qwen_trial.sqlite focus --limit 20
```

The small model is expected to be noisy. It is a scout. Use `show` to inspect
why it kept an atom:

```powershell
python -m sporepath --db qwen_trial.sqlite show <atom-id>
```

## Digested Notes

Raw conversations are too long to review. Thought atoms are useful for scoring
and linking, but too small to read as notes. Digested notes are the middle
layer:

```text
raw chat / JSONL
    -> thought atoms
    -> digested notes
    -> focus and latent graph
```

Build notes from the atoms already in your database:

```powershell
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite notes
python -m sporepath --db my_memory.sqlite show-note <note-id>
```

Current note generation is deliberately simple and local. It groups atoms by
topic, keeps source atom ids and source spans, and produces rough note types:

- `concept_note`
- `decision_note`
- `friction_note`

These notes are not treated as permanent truth. They are readable byproducts of
the memory metabolism layer, and can be rebuilt as extraction improves.

## Refresh Pipeline

`refresh` is the one-step pipeline behind the desktop button:

```powershell
python -m sporepath --db my_memory.sqlite refresh `
  --input "$env:USERPROFILE\Downloads\conversations.json" `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph sporepath_graph.html
```

If your database already has atoms, `--input` is optional. Without it, refresh
rebuilds edges, notes, vault export, and graph from the existing database.

You can also ask Sporepath to detect Codex/Claude sources:

```powershell
python -m sporepath sources
python -m sporepath --db my_memory.sqlite refresh --source codex --source claude `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph sporepath_graph.html
```

`--source` is explicit on purpose. A plain `refresh` does not scan your
home directory unless you ask for sources.

## Obsidian Vault Export

Sporepath does not need to become a note-taking app. It can export digested
notes into a plain Markdown vault that Obsidian can open directly:

```powershell
python -m sporepath --db my_memory.sqlite export-vault "$env:USERPROFILE\Documents\Sporepath Vault"
```

The export writes:

```text
Sporepath Vault/
  Digested Notes/
    concept-note-memory-metabolism-abc1234.md
  .sporepath/
    manifest.json
```

Each note includes YAML frontmatter with `sporepath_id`, `type`, `state`,
`activation`, `tags`, `source_atoms`, and `source_spans`. Obsidian is the human
reading/editing surface; SQLite remains the source of truth for activation,
focus/latent scoring, and future inspire behavior.

If you edit generated notes in Obsidian, sync that activity back into the
metabolism layer:

```powershell
python -m sporepath --db my_memory.sqlite sync-vault "$env:USERPROFILE\Documents\Sporepath Vault"
```

`sync-vault` compares the exported manifest with current Markdown files. Modified
notes touch their source atoms, so Obsidian edits become path-strength feedback.

## Inspiration Bridge

`inspire` sends a compact prompt to `codex exec`. The adapter removes
`CODEX_API_KEY` and `OPENAI_API_KEY` from the child process environment, uses
stdin for the prompt, runs read-only, and lowers reasoning effort for this PoC.

Check auth first:

```powershell
python -m sporepath doctor
```

You want Codex to report ChatGPT login if you intend to use subscription usage
instead of API-key billing.

Dry run:

```powershell
python -m sporepath --db my_memory.sqlite inspire "I am stuck on how to validate this project" --dry-run
```

Real run:

```powershell
python -m sporepath --db my_memory.sqlite inspire "I am stuck on how to validate this project" --focus-limit 5 --latent-limit 10
```

## Graph

```powershell
python -m sporepath --db my_memory.sqlite graph --out graph.html --limit 160
```

In the graph:

- circle = thought atom
- line = shared-tag path
- larger/brighter circle = stronger focus path
- faded amber circle = latent path
- click a node = inspect source, tags, activation, and original text

The graph is a standalone local HTML file. It embeds excerpts from your memory
database, so treat it as private data.

## Privacy

This project is designed for local-first experimentation, but your imported
chat logs can contain sensitive personal or work data.

Do not commit:

- `*.sqlite`
- generated graph HTML files
- real chat exports
- Codex/Claude/ChatGPT auth files

The `.gitignore` is set up to ignore the common generated files, but review
`git status` before publishing.

## Current Limits

- Edges currently include shared-tag evidence and confidence metadata, but they
  are still not true semantic embeddings.
- `qwen3:1.7b` can extract useful candidates, but it also creates noise.
- `digest` is currently rules-based grouping, not high-quality editorial
  summarization.
- `sync-vault` only uses generated-note file edits as feedback; this is not a
  full Obsidian plugin or bidirectional sync engine.
- The desktop window is a local tkinter launcher, not a packaged Windows
  installer yet.
- There is no eval UI yet; manual inspection with `focus` and `show` is still
  required.
- Archive/deep-archive budgets are design goals, not complete product features.
- The graph is a static HTML export, not a full app.

## Test

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## Project Direction

The next important question is not whether a 1B model can summarize chat logs.
It is whether a small local model can extract reusable structures that the
memory graph can later validate through use:

- friction structures
- state machines
- decision questions
- taste and judgment patterns
- recurring technical pitfalls

If you try this on your own logs, issues with real examples of noisy extraction,
missed useful atoms, or graph behavior are the most valuable feedback.
