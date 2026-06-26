# Sporepath

[繁體中文](README.zh-TW.md)

![A small Sporepath scout organizes AI chat fragments into focus paths and latent idea spores](assets/hero-mascot.png)

Local-first experiment for turning AI chat history into a living memory graph.
After testing the idea against ArcRift, Sporepath is intentionally shifting
toward a companion role: let ArcRift handle capture, RAG, MCP, and context
injection; let Sporepath digest those memories into notes, metabolic focus
paths, and weird-but-bridged inspiration prompts.

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

- Imports ChatGPT-style `conversations.json`, generic JSONL chat logs,
  allowlisted local Codex/Claude conversation stores, and ArcRift SQLite
  `full_chats`.
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

This starts the ArcRift backend if needed, starts minimized Sporepath watchers,
and opens the small local Sporepath window.

- Local Codex/Claude/jsonl sources are watched directly. When those files
  change, Sporepath refreshes the SQLite memory, digested notes, Obsidian vault,
  and graph.
- The background digestion queue worker is started minimized. It only processes
  queued fragments during the configured off-peak window.
- Web chats are intentionally not scraped in the background. After a ChatGPT or
  Claude web conversation, press ArcRift's popup **Save Chat** button. Once
  ArcRift writes the chat into `ArcRift.db`, Sporepath imports it through the
  same refresh pipeline.

The window still exposes the everyday actions:

- **Refresh Now**: rebuild notes, export the Obsidian vault, and refresh the graph.
- **Import ArcRift**: import ArcRift `full_chats` from a selected SQLite DB, then rebuild notes, vault, and graph.
- **Sync Vault**: treat edited Obsidian notes as usage feedback and thicken their source atoms.
- **Open Vault**: open the Markdown vault folder for Obsidian.
- **Queue Status**: show pending, done, skipped, and error counts for background digestion.
- **Run Queue Batch**: enqueue the selected chat export or detected local sources, then process a small rules-baseline batch.
- **Inspire**: enter a stuck question and ask Codex for weird-but-bridged next moves.
- **Mark Useful**: enter a returned suggestion id and thicken the bridge that actually helped.

The batch launcher uses `real_memory.sqlite` in this checkout by default. The
window still lets you edit the DB, chat export, vault, and graph paths before
running anything.

If you only want the backend without opening Sporepath:

```text
Start-ArcRift.bat
```

If you only want the off-peak queue worker:

```text
Run-Sporepath-Queue-Worker.bat
```

It defaults to `qwen3.5:4b`, `00:00-07:00`, batch size `5`, auto-feeds
allowlisted local sources with `--source all`, refreshes the Obsidian vault and
HTML graph after new atoms are created, and checks that Ollama and the model
exist before starting.

To start that worker automatically when Windows logs in, run:

```text
Install-Sporepath-Queue-Worker-Task.bat
```

To remove the scheduled task:

```text
Uninstall-Sporepath-Queue-Worker-Task.bat
```

If Chrome's extension manager is inconvenient, there are best-effort launchers:

```text
Launch-ArcRift-Chrome.bat
```

It tries to open a separate Chrome profile at
`%LOCALAPPDATA%\Sporepath\ArcRift Chrome Profile` with the local ArcRift
extension loaded from `..\ArcRift\extension\dist\chrome`. Google Chrome can
ignore `--load-extension` in some installs, so the reliable setup is still to
load the unpacked ArcRift extension manually once from `chrome://extensions`.
You may need to sign in to ChatGPT/Claude once in that dedicated profile.

If you want to reuse your existing logged-in Chrome profile instead, use:

```text
Launch-ArcRift-Logged-In-Chrome.bat
```

This closes Chrome, then tries to reopen the `Default` profile with the ArcRift
extension loaded. It is useful when ChatGPT/Claude are already signed in in your
normal browser, but it will close any current Chrome windows first. If Chrome
ignores the extension flag, manually install the unpacked ArcRift extension once
and keep using your normal browser.

Use **Auto-detect Sources** to find local Codex and Claude conversation stores,
or let the source watcher do it automatically. Sporepath only uses an allowlist
of likely conversation sources:

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

## Background Digestion Queue

Slow scout models do not need to run while you are working. Queue new chat
fragments first, then digest them later during idle/off-peak time:

```powershell
python -m sporepath --db real_memory.sqlite queue-build --source all --min-chars 80
python -m sporepath --db real_memory.sqlite queue-stats
```

Queue collection is intentionally conservative. It skips near-duplicate
fragments and disposable command/recap noise before the local scout sees them.
Use `--no-dedupe` only when you intentionally want to test repeated cases.

Process a small batch with the rules baseline:

```powershell
python -m sporepath --db real_memory.sqlite digest-queue --extractor rules --limit 25
```

Process a slower local scout such as `qwen3.5:4b`:

```powershell
python -m sporepath --db real_memory.sqlite digest-queue `
  --extractor ollama `
  --model qwen3.5:4b `
  --ollama-timeout-s 180 `
  --ollama-num-predict 320 `
  --limit 10
```

Each fragment is checkpointed as `done`, `skipped`, or `error`, so an interrupted
run can continue later without reprocessing finished items.
If a model call failed, inspect and retry errors without opening SQLite:

```powershell
python -m sporepath --db real_memory.sqlite queue-errors
python -m sporepath --db real_memory.sqlite queue-retry
```

To leave a worker running and only process the queue during off-peak hours:

```powershell
python -m sporepath --db real_memory.sqlite queue-worker `
  --source all `
  --off-peak 00:00-07:00 `
  --batch-size 5 `
  --interval-s 300 `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph real_graph.html `
  --extractor ollama `
  --model qwen3.5:4b `
  --ollama-timeout-s 180 `
  --ollama-num-predict 320
```

Use `--once --run-now` to run one batch immediately for testing.
`Run-Sporepath-Queue-Worker.bat` is the copy-paste version of this flow.

## ArcRift Companion Mode

ArcRift already does a better job at capture, RAG, MCP, graph dashboard, and
context injection than this small repo should try to reimplement. Sporepath can
use ArcRift as the memory source and stay focused on the layer ArcRift does not
center: readable digestion, path metabolism, and `inspire`.

Point Sporepath at an ArcRift SQLite database:

```powershell
$arc = Read-Host "Paste the full path to ArcRift.db"
python -m sporepath --db my_memory.sqlite import-arcrift $arc
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite export-vault "$env:USERPROFILE\Documents\Sporepath Vault"
python -m sporepath --db my_memory.sqlite inspire "I am stuck on what to do next"
```

If you run ArcRift from its repo, the default SQLite file is usually
`ArcRift.db` in the backend working directory unless `SQLITE_DB_PATH` is set.
Sporepath opens the ArcRift DB in read-only mode and imports from
`full_chats.rawText`; it does not modify ArcRift's database.

Filter to one ArcRift project or session id:

```powershell
python -m sporepath --db my_memory.sqlite import-arcrift $arc --project "My Project"
```

To keep Sporepath updated automatically after ArcRift saves chats:

```powershell
python -m sporepath --db real_memory.sqlite watch-arcrift `
  --arcrift-db "$env:USERPROFILE\Desktop\GH_repos\ArcRift\backend\ArcRift.db" `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph real_graph.html
```

On this machine, `Sporepath.bat` starts that watcher for you.

To open a Chrome profile with the ArcRift extension already loaded:

```text
Launch-ArcRift-Chrome.bat
```

To reuse the already signed-in Chrome `Default` profile, close/reopen Chrome and
load the extension in one step:

```text
Launch-ArcRift-Logged-In-Chrome.bat
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

To keep local Codex/Claude/jsonl sources synced without pressing Refresh Now:

```powershell
python -m sporepath --db real_memory.sqlite watch-sources --source all `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph real_graph.html
```

On Windows, `Run-Sporepath-Sources-Watcher.bat` runs that command, and
`Sporepath.bat` starts it for you.

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

Successful runs print an `inspire_run=<id>` line. When the generated text
includes `suggestion_id` and `cited_atom_ids`, Sporepath stores that mapping so
you can mark a useful idea without retyping atom ids:

```powershell
python -m sporepath --db my_memory.sqlite inspire-feedback <run-id> `
  --status useful `
  --suggestion 1 `
  --note "This bridge changed the next step"
```

You can still mark a bridge manually by passing the cited atoms:

```powershell
python -m sporepath --db my_memory.sqlite inspire-feedback <run-id> `
  --status useful `
  --atoms <atom-id-1> <atom-id-2> `
  --note "This bridge changed the next step"
```

Positive feedback statuses are `selected`, `useful`, and `applied`. They thicken
the selected atoms and add or strengthen an `inspire_feedback` bridge between
them. `boring`, `wrong`, and `ignored` are recorded but do not thicken the path.

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

## Extraction Eval

Use this before trusting a small local model as a scout. It builds a review
sheet from real chat fragments, runs the rules baseline or Ollama extractor,
and leaves blank human fields for scoring.

```powershell
$env:PYTHONPATH = "src"
python -m sporepath eval-extract --source codex --limit 20 `
  --contains debug --contains bug --contains error `
  --max-chars 1200 `
  --out eval\codex_eval.jsonl `
  --report eval\codex_eval.md
```

To test a local model:

```powershell
python -m sporepath eval-extract --source codex --limit 20 `
  --contains debug --contains bug --contains error `
  --extractor ollama --model qwen3:1.7b `
  --max-chars 1200 `
  --out eval\qwen_eval.jsonl `
  --report eval\qwen_eval.md
```

For the current middle-ground scout, run:

```text
Run-Sporepath-Qwen35-Eval.bat
```

That samples 50 allowlisted local sources with `qwen3.5:4b`, caps the sample at
one case per file, skips near-duplicates, checkpoints after every case, and writes
`eval\qwen35_4b_eval.jsonl` plus `eval\qwen35_4b_eval.md`. It then runs
`eval-clean` and writes `eval\qwen35_4b_eval.clean.jsonl` plus
`eval\qwen35_4b_eval.clean.md`; review and score the clean sheet first.

After reviewing the Markdown, fill the `human` fields in the JSONL file, then
summarize:

```powershell
python -m sporepath eval-score eval\qwen_eval.jsonl
```

If the sheet contains repeated fragments, clean it without losing the `human`
review fields:

```powershell
python -m sporepath eval-clean eval\qwen_eval.jsonl `
  --out eval\qwen_eval.clean.jsonl `
  --report eval\qwen_eval.clean.md
```

The human part should stay narrow. Do not judge whether the model wrote a good
note. Judge whether it behaved like a useful scout:

- `keep`: should this fragment be kept?
- `route`: debug, product, preference, idea, decision, research, writing, ops, or other.
- `signal_found`: did it catch the reusable signal?
- `noise_marked`: did it mark obvious disposable noise?
- `handoff_sufficient`: is the handoff enough for a cloud model to think with later?

The command reports pass rate, keep agreement, route agreement, signal-found
rate, noise-marked rate, and handoff-sufficient rate.

## Validators

Sporepath's goal is not "store every chat forever." A useful build should pass
three narrower checks:

- **Scout quality**: the local scout keeps reusable fragments, rejects tool
  noise, and writes a handoff that is good enough for a cloud model later.
- **Note usability**: digested notes are not empty, keep their source anchors,
  and do not collapse into duplicate titles.
- **Inspire feedback**: `inspire` runs produce suggestions that you actually
  mark as useful often enough to justify the workflow.

Run the checks separately:

```powershell
python -m sporepath validate-scout eval\qwen_eval.jsonl --out eval\validation_scout.md
python -m sporepath --db my_memory.sqlite validate-notes --out eval\validation_notes.md
python -m sporepath --db my_memory.sqlite validate-inspire --out eval\validation_inspire.md
```

Use the cleaned sheet for `validate-scout` when `eval-clean` drops duplicates:

```powershell
python -m sporepath validate-scout eval\qwen_eval.clean.jsonl --out eval\validation_scout.md
```

Or write one combined report:

```powershell
python -m sporepath --db my_memory.sqlite validate-report `
  --scout-eval eval\qwen_eval.jsonl `
  --out eval\sporepath_validation.md
```

Verdicts are deliberately conservative:

- `pass`: the measured health checks are above the current target.
- `fail`: the data exists, but at least one target is below the line.
- `needs_data`: the validator cannot judge yet because the repo has not
  collected enough scored eval rows, generated notes, or inspire feedback.

These validators are meant to catch structural problems. They still do not
replace the human judgment step: only you can say whether a note feels worth
opening again or whether an inspired move changed the next action.

## Current Limits

- Edges currently include shared-tag evidence and confidence metadata, but they
  are still not true semantic embeddings.
- `qwen3:1.7b` can extract useful candidates, but it also creates noise.
- ArcRift import currently reads `full_chats.rawText` only; it does not import
  ArcRift facts, vector chunks, or retrieval scores yet.
- `digest` is currently rules-based grouping, not high-quality editorial
  summarization.
- `sync-vault` only uses generated-note file edits as feedback; this is not a
  full Obsidian plugin or bidirectional sync engine.
- The desktop window is a local tkinter launcher, not a packaged Windows
  installer yet.
- Extraction eval exists as CLI-generated JSONL/Markdown sheets, but there is
  no graphical eval UI yet.
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
