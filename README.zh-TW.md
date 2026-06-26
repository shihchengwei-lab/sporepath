# Sporepath

[English](README.md)

![一隻小小的 Sporepath scout 把 AI 對話碎片整理成專注路徑與潛在靈感孢子](assets/hero-mascot.png)

Sporepath 是一個 local-first 實驗：把你和 AI 的聊天紀錄，轉成一張會代謝的記憶圖。

它不是另一個筆記庫。它想驗證的是：過去聊天裡留下的想法碎片，能不能變成兩層有用的思考路徑：

- **專注路徑**：最近常用、常被碰到的想法會變粗，幫你延續當下正在研究的脈絡。
- **潛在路徑**：暫時用不到、低活性的想法會沉下去，不干擾你，但未來遇到新問題時可以被重新喚醒。

小型本地模型在這裡不是「真正的大腦」，而是 scout。它負責從聊天紀錄裡找出候選的 thought atoms；真正決定哪些路徑變粗、淡掉、沉入封存的，是本地規則和後續使用訊號。

## 它現在能做什麼

- 匯入 ChatGPT 風格的 `conversations.json`、一般 JSONL 聊天紀錄、白名單中的本地 Codex/Claude 對話來源，以及 ArcRift SQLite `full_chats`。
- 用兩種方式抽取 `thought atoms`：
  - 規則版 baseline。
  - 本地 Ollama 模型，例如 `qwen3:1.7b`。
- 把 thought atoms 和共享標籤邊存進 SQLite。
- 從 atoms 聚合出可讀的 `digested notes`，讓你不用打開整份對話紀錄也能回看。
- 把 digested notes 匯出成 Obsidian 可直接打開的本地 Markdown vault。
- 追蹤 `activation`，也就是粗略的路徑強度。
- 產生本地互動 HTML 記憶圖。
- 只有 `inspire` 這個靈感橋接功能會呼叫 `codex exec`，讓你可以走既有 ChatGPT/Codex 訂閱額度，而不是 API key。

## 安裝

```powershell
git clone https://github.com/shihchengwei-lab/sporepath.git
cd sporepath
python -m pip install -e .
```

也可以不安裝，直接從 repo 裡跑：

```powershell
$env:PYTHONPATH = "src"
python -m sporepath doctor
```

## 低摩擦桌面流程

在 Windows 上可以直接雙擊：

```text
Sporepath.bat
```

它現在會先啟動 ArcRift backend，再啟動最小化的 Sporepath watchers，最後打開 Sporepath 小視窗。

- 本地 Codex / Claude / jsonl 來源會直接被 watcher 追蹤。檔案有變動時，Sporepath 會自動刷新 SQLite 記憶庫、digested notes、Obsidian vault 和 graph。
- 背景消化 queue worker 會以最小化視窗啟動，只在設定的離峰時段處理 queued fragments。
- 網頁聊天不再做背景自動抓取。你聊完 ChatGPT 或 Claude 網頁版之後，按 ArcRift popup 裡的 **Save Chat**。ArcRift 把聊天寫進 `ArcRift.db` 後，Sporepath 會走同一條管線把它變成本地筆記。

如果只想啟動 ArcRift backend，可以執行：

```text
Start-ArcRift.bat
```

如果只想啟動離峰 queue worker，可以執行：

```text
Run-Sporepath-Queue-Worker.bat
```

預設會用 `qwen3.5:4b`、`00:00-07:00`、每批 `5` 筆，並用 `--source all` 自動收白名單裡的本地 Codex/Claude/jsonl 對話來源。處理出新 atoms 後，也會刷新 Obsidian vault 和 HTML graph。啟動前會先檢查 Ollama 和模型是否存在，避免模型沒裝時把 queue 項目標成錯誤。

如果想讓 Windows 登入時自動啟動這個 worker，可以執行：

```text
Install-Sporepath-Queue-Worker-Task.bat
```

要移除排程：

```text
Uninstall-Sporepath-Queue-Worker-Task.bat
```

如果不想手動進 Chrome extension manager，可以試試這兩個 best-effort launcher：

```text
Launch-ArcRift-Chrome.bat
```

它會嘗試開一個專用 Chrome profile：
`%LOCALAPPDATA%\Sporepath\ArcRift Chrome Profile`，並載入本機 ArcRift extension：`..\ArcRift\extension\dist\chrome`。但有些 Google Chrome 安裝會忽略 `--load-extension`，所以最可靠的方式仍然是到 `chrome://extensions` 手動載入 unpacked ArcRift extension 一次。你可能需要在這個專用 profile 裡登入一次 ChatGPT/Claude。

如果你想沿用平常 Chrome 裡已經登入的 ChatGPT/Claude，可以執行：

```text
Launch-ArcRift-Logged-In-Chrome.bat
```

它會先關掉目前的 Chrome，然後嘗試用 `Default` profile 重新開啟，並載入 ArcRift extension。這條路可以沿用既有登入狀態，但會先關閉目前所有 Chrome 視窗。如果 Chrome 忽略 extension 參數，就手動安裝 unpacked ArcRift extension 一次，之後照常用平常的瀏覽器。

它會打開一個本地小視窗，日常只需要三個動作：

- **Refresh Now**：重建 notes、匯出 Obsidian vault、更新 graph。
- **Import ArcRift**：從指定 SQLite DB 匯入 ArcRift `full_chats`，然後重建 notes、vault 和 graph。
- **Sync Vault**：把 Obsidian 裡改過的 notes 視為使用回饋，回流加粗 source atoms。
- **Open Vault**：打開 Markdown vault 資料夾，讓 Obsidian 使用。
- **Queue Status**：查看背景消化 queue 的 pending、done、skipped、error 數量。
- **Run Queue Batch**：把目前聊天匯出檔或已偵測來源補進 queue，然後用 rules baseline 手動處理一小批。
- **Inspire**：輸入卡住的問題，請 Codex 產生「怪但有橋」的下一手。
- **Mark Useful**：輸入某個 `suggestion_id`，把真的有幫助的靈感橋加粗。

這個 batch launcher 預設使用 repo 裡的 `real_memory.sqlite`。視窗裡仍然可以修改 DB、聊天匯出檔、vault 和 graph 路徑。

按 **Auto-detect Sources** 可以尋找本機 Codex 和 Claude 的對話來源，也可以交給 source watcher 自動追蹤。Sporepath 只使用白名單中的可能對話來源：

```text
{home}/.codex/history.jsonl
{home}/.codex/sessions/
{home}/.codex/archived_sessions/
{home}/.claude/history.jsonl
{home}/.claude/projects/
{home}/.claude/sessions/
```

它會刻意忽略 credentials、auth、settings、logs、cache 和其他非對話檔案。

## 快速測試

先用內建 sample 試跑：

```powershell
$env:PYTHONPATH = "src"
python -m sporepath --db sample_memory.sqlite ingest examples\sample_chat.jsonl
python -m sporepath --db sample_memory.sqlite digest
python -m sporepath --db sample_memory.sqlite notes
python -m sporepath --db sample_memory.sqlite focus
python -m sporepath --db sample_memory.sqlite graph --out graph.html
```

接著用瀏覽器打開 `graph.html`。

## 匯入自己的聊天紀錄

如果你的 ChatGPT 匯出檔在 Downloads：

```powershell
$chat = "$env:USERPROFILE\Downloads\conversations.json"
python -m sporepath --db my_memory.sqlite ingest $chat
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite notes
python -m sporepath --db my_memory.sqlite stats
python -m sporepath --db my_memory.sqlite focus
```

先用本地小模型跑一小段就好：

```powershell
ollama pull qwen3:1.7b
$chat = "$env:USERPROFILE\Downloads\chat.jsonl"
python -m sporepath --db qwen_trial.sqlite ingest $chat --extractor ollama --model qwen3:1.7b --max-turns 50
python -m sporepath --db qwen_trial.sqlite focus --limit 20
```

## ArcRift Companion Mode

ArcRift 已經把 capture、RAG、MCP、graph dashboard、context injection 做得比這個小 repo 更完整。Sporepath 接下來不要跟它正面重造底層輪子，而是把 ArcRift 當成記憶來源，自己專注在 ArcRift 沒有主打的那一層：可讀筆記消化、路徑代謝，以及 `inspire` 的「怪但有橋」下一手。

指定 ArcRift 的 SQLite DB：

```powershell
$arc = Read-Host "Paste the full path to ArcRift.db"
python -m sporepath --db my_memory.sqlite import-arcrift $arc
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite export-vault "$env:USERPROFILE\Documents\Sporepath Vault"
python -m sporepath --db my_memory.sqlite inspire "我現在卡住了，下一步該做什麼"
```

如果你是從 ArcRift repo 啟動，預設 SQLite 通常會在 backend 的工作目錄裡叫 `ArcRift.db`，除非你有設定 `SQLITE_DB_PATH`。Sporepath 會用唯讀模式打開 ArcRift DB，只讀 `full_chats.rawText`，不會修改 ArcRift 的資料庫。

只匯入某個 ArcRift project 或 session id：

```powershell
python -m sporepath --db my_memory.sqlite import-arcrift $arc --project "My Project"
```

如果要讓 Sporepath 在 ArcRift 存入新聊天後自動同步：

```powershell
python -m sporepath --db real_memory.sqlite watch-arcrift `
  --arcrift-db "$env:USERPROFILE\Desktop\GH_repos\ArcRift\backend\ArcRift.db" `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph real_graph.html
```

在這台機器上，`Sporepath.bat` 已經會替你啟動這個 watcher。

如果要打開已載入 ArcRift extension 的專用 Chrome：

```text
Launch-ArcRift-Chrome.bat
```

如果要沿用已登入的平常 Chrome profile，並在重開時載入 ArcRift extension：

```text
Launch-ArcRift-Logged-In-Chrome.bat
```

小模型一定會有雜訊。它只是 scout，不是裁判。可以用 `show` 檢查它為什麼留下某個 atom：

```powershell
python -m sporepath --db qwen_trial.sqlite show <atom-id>
```

## 背景消化 Queue

慢 scout 不需要在你工作時即時跑。可以先把新聊天片段放進 queue，等離峰或電腦閒置時再慢慢整理：

```powershell
python -m sporepath --db real_memory.sqlite queue-build --source all --min-chars 80
python -m sporepath --db real_memory.sqlite queue-stats
```

queue 收片段預設是保守的：會先跳過近似重複片段，以及一次性命令、recap 這類可丟噪音。這是刻意遺忘；只有在你故意想測重複案例時才加 `--no-dedupe`。

先用 rules baseline 處理一小批：

```powershell
python -m sporepath --db real_memory.sqlite digest-queue --extractor rules --limit 25
```

用比較慢的本地 scout，例如 `qwen3.5:4b`：

```powershell
python -m sporepath --db real_memory.sqlite digest-queue `
  --extractor ollama `
  --model qwen3.5:4b `
  --ollama-timeout-s 180 `
  --ollama-num-predict 320 `
  --limit 10
```

每個片段都會 checkpoint 成 `done`、`skipped` 或 `error`。中途停掉也沒關係，下次可以接著處理還沒完成的 backlog。

如果想讓 worker 掛著，只在離峰時段處理 queue：

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

每個片段都會 checkpoint 成 `done`、`skipped` 或 `error`。如果模型呼叫失敗，可以不用打開 SQLite，直接查看和重排：

```powershell
python -m sporepath --db real_memory.sqlite queue-errors
python -m sporepath --db real_memory.sqlite queue-retry
```

要測試時可以加 `--once --run-now`，立刻跑一批就結束。`Run-Sporepath-Queue-Worker.bat` 是這段流程的可雙擊版本。

## 代謝後的筆記

完整聊天紀錄太長，不適合回看。Thought atoms 很適合拿來計分和連線，但太碎，不適合直接閱讀。Digested notes 是中間層：

```text
raw chat / JSONL
    -> thought atoms
    -> digested notes
    -> focus and latent graph
```

從現有 atoms 產生可讀筆記：

```powershell
python -m sporepath --db my_memory.sqlite digest
python -m sporepath --db my_memory.sqlite notes
python -m sporepath --db my_memory.sqlite show-note <note-id>
```

目前 notes 產生方式刻意保持簡單且本地化。它會按主題聚合 atoms，保留來源 atom id 和 source span，並先分成幾種粗略型態：

- `concept_note`
- `decision_note`
- `friction_note`

這些筆記不是永久真相，而是記憶代謝後產生的可讀副產物。未來抽取品質變好時，可以重新 build。

## Refresh 管線

`refresh` 是桌面視窗背後的一鍵管線：

```powershell
python -m sporepath --db my_memory.sqlite refresh `
  --input "$env:USERPROFILE\Downloads\conversations.json" `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph sporepath_graph.html
```

如果資料庫裡已經有 atoms，`--input` 可以省略。這時 refresh 會直接用現有資料重建 edges、notes、vault 匯出和 graph。

也可以請 Sporepath 偵測 Codex / Claude 來源：

```powershell
python -m sporepath sources
python -m sporepath --db my_memory.sqlite refresh --source codex --source claude `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph sporepath_graph.html
```

`--source` 是刻意要求明確指定的。單純 `refresh` 不會自己掃你的 home directory。

如果想讓本地 Codex / Claude / jsonl 來源不用手動按 Refresh Now 就同步：

```powershell
python -m sporepath --db real_memory.sqlite watch-sources --source all `
  --vault "$env:USERPROFILE\Documents\Sporepath Vault" `
  --graph real_graph.html
```

在 Windows 上，`Run-Sporepath-Sources-Watcher.bat` 會跑這條指令，`Sporepath.bat` 也會自動啟動它。

## Obsidian Vault 匯出

Sporepath 不需要自己變成筆記軟體。它可以把 digested notes 匯出成純 Markdown vault，讓 Obsidian 直接打開：

```powershell
python -m sporepath --db my_memory.sqlite export-vault "$env:USERPROFILE\Documents\Sporepath Vault"
```

匯出結果會長這樣：

```text
Sporepath Vault/
  Digested Notes/
    concept-note-memory-metabolism-abc1234.md
  .sporepath/
    manifest.json
```

每份筆記都會帶 YAML frontmatter，包括 `sporepath_id`、`type`、`state`、`activation`、`tags`、`source_atoms` 和 `source_spans`。Obsidian 負責給人閱讀、搜尋、修改；SQLite 仍然是 activation、專注/潛在分數和未來 inspire 行為的真相來源。

如果你在 Obsidian 裡修改了產生出的筆記，可以把這個使用訊號同步回代謝層：

```powershell
python -m sporepath --db my_memory.sqlite sync-vault "$env:USERPROFILE\Documents\Sporepath Vault"
```

`sync-vault` 會比較 export manifest 和目前 Markdown 檔案。被修改過的 notes 會 touch 它們的 source atoms，讓 Obsidian 編輯變成路徑加粗訊號。

## 靈感橋接

`inspire` 會把目前的專注路徑和潛在候選片段整理成一個短 prompt，送給 `codex exec`。這個 PoC 會移除子程序裡的 `CODEX_API_KEY` 和 `OPENAI_API_KEY`，用 stdin 傳 prompt，並以唯讀方式執行。

先檢查本機狀態：

```powershell
python -m sporepath doctor
```

如果你想走訂閱額度而不是 API 計費，要確認 Codex 顯示的是 ChatGPT 登入狀態。

先看 dry run：

```powershell
python -m sporepath --db my_memory.sqlite inspire "我現在卡在這個第二大腦 PoC 要怎麼驗證價值" --dry-run
```

真的執行：

```powershell
python -m sporepath --db my_memory.sqlite inspire "我現在卡在這個第二大腦 PoC 要怎麼驗證價值" --focus-limit 5 --latent-limit 10
```

成功執行後會印出一行 `inspire_run=<id>`。如果輸出裡有 `suggestion_id` 和 `cited_atom_ids`，Sporepath 會記住這個對照，所以你可以直接標記哪個靈感有用，不必手動複製 atom ids：

```powershell
python -m sporepath --db my_memory.sqlite inspire-feedback <run-id> `
  --status useful `
  --suggestion 1 `
  --note "這條橋改變了下一步"
```

也可以手動指定被引用的 atoms：

```powershell
python -m sporepath --db my_memory.sqlite inspire-feedback <run-id> `
  --status useful `
  --atoms <atom-id-1> <atom-id-2> `
  --note "這條橋改變了下一步"
```

正向狀態是 `selected`、`useful`、`applied`。它們會加粗選中的 atoms，並在它們之間新增或加強 `inspire_feedback` bridge。`boring`、`wrong`、`ignored` 只會記錄，不會加粗路徑。

## 記憶圖

```powershell
python -m sporepath --db my_memory.sqlite graph --out graph.html --limit 160
```

圖上的意思：

- 圓點 = thought atom。
- 線 = 共享標籤形成的路徑。
- 越大、越亮的圓點 = 越強的專注路徑。
- 淡琥珀色圓點 = 潛在路徑。
- 點擊節點 = 查看來源、標籤、activation 和原文。

這張圖是本地 standalone HTML，裡面會嵌入你的記憶庫片段，所以請把它當成私有資料。

## 隱私

這個專案是 local-first，但你的聊天紀錄可能包含個人或工作敏感資料。

不要 commit：

- `*.sqlite`
- 產生出來的 graph HTML
- 真實聊天匯出檔
- Codex、Claude、ChatGPT 的登入或憑證檔

`.gitignore` 已經擋掉常見產物，但公開前仍然請看一次 `git status`。

## 抽取品質 Eval

在相信本地小模型能當 scout 之前，先用真實聊天片段做這個檢查。它會產生一份 JSONL 打分表和一份 Markdown review sheet，先跑 rules baseline 或 Ollama extractor，並留下 human 欄位給人評分。

```powershell
$env:PYTHONPATH = "src"
python -m sporepath eval-extract --source codex --limit 20 `
  --contains debug --contains bug --contains error `
  --max-chars 1200 `
  --out eval\codex_eval.jsonl `
  --report eval\codex_eval.md
```

測本地小模型：

```powershell
python -m sporepath eval-extract --source codex --limit 20 `
  --contains debug --contains bug --contains error `
  --extractor ollama --model qwen3:1.7b `
  --max-chars 1200 `
  --out eval\qwen_eval.jsonl `
  --report eval\qwen_eval.md
```

目前要測中庸一點的 scout，可以直接跑：

```text
Run-Sporepath-Qwen35-Eval.bat
```

它會用 `qwen3.5:4b` 從白名單本地來源抽 50 筆、每個檔案最多 1 筆，跳過近似重複片段，並且每完成 1 筆就 checkpoint。輸出是 `eval\qwen35_4b_eval.jsonl` 和 `eval\qwen35_4b_eval.md`。接著它會自動跑 `eval-clean`，另外輸出 `eval\qwen35_4b_eval.clean.jsonl` 和 `eval\qwen35_4b_eval.clean.md`；請優先看 clean sheet 並補評分。

看完 Markdown 後，把 JSONL 裡的 `human` 欄位補上，再統計：

```powershell
python -m sporepath eval-score eval\qwen_eval.jsonl
```

如果打分表裡有重複片段，可以先清掉，不會丟掉留下來那筆的 `human` 評分：

```powershell
python -m sporepath eval-clean eval\qwen_eval.jsonl `
  --out eval\qwen_eval.clean.jsonl `
  --report eval\qwen_eval.clean.md
```

human-in-the-loop 只需要評很窄的東西，不評小模型有沒有寫出漂亮筆記，而是評它有沒有做好 scout：

- `keep`：這段該不該留下？
- `route`：debug、product、preference、idea、decision、research、writing、ops、other。
- `signal_found`：有沒有抓到可重用訊號？
- `noise_marked`：有沒有標出明顯該丟掉的雜訊？
- `handoff_sufficient`：這份 handoff 夠不夠讓雲端模型之後拿去思考？

指令會統計 pass rate、keep agreement、route agreement、signal-found rate、noise-marked rate 和 handoff-sufficient rate。

## Validator

Sporepath 的目標不是「把所有聊天永久存起來」。目前比較務實的好壞標準有三個：

- **Scout 品質**：本地小模型要能留下可重用片段、擋掉工具雜訊，並寫出足夠讓雲端模型之後接手思考的 handoff。
- **筆記可用性**：整理出的筆記不能是空殼，要保留來源錨點，也不能一直產生重複標題。
- **靈感回饋**：`inspire` 產生的下一手，要有一定比例真的被你標成有用，否則這套流程只是好看。

分開檢查：

```powershell
python -m sporepath validate-scout eval\qwen_eval.jsonl --out eval\validation_scout.md
python -m sporepath --db my_memory.sqlite validate-notes --out eval\validation_notes.md
python -m sporepath --db my_memory.sqlite validate-inspire --out eval\validation_inspire.md
```

如果 `eval-clean` 有清掉重複片段，`validate-scout` 請改用 cleaned sheet：

```powershell
python -m sporepath validate-scout eval\qwen_eval.clean.jsonl --out eval\validation_scout.md
```

也可以產生一份總報告：

```powershell
python -m sporepath --db my_memory.sqlite validate-report `
  --scout-eval eval\qwen_eval.jsonl `
  --out eval\sporepath_validation.md
```

目前 verdict 有三種：

- `pass`：已量到的健康檢查都過目前門檻。
- `fail`：有資料可以判斷，但至少一個門檻沒過。
- `needs_data`：資料還不夠，例如沒有人工評過的 eval、沒有產生筆記，或沒有 inspire feedback。

這些 validator 只能抓結構問題，不能取代人的判斷。筆記值不值得再打開、某個靈感有沒有改變下一步，最後還是要由你標記。

## 目前限制

- 目前的 edges 已經帶 shared-tag evidence 和 confidence metadata，但仍然不是真正的語意 embedding。
- `qwen3:1.7b` 可以抽出有用候選，但也會製造雜訊。
- ArcRift import 目前只讀 `full_chats.rawText`；還沒有匯入 ArcRift facts、vector chunks 或 retrieval scores。
- `digest` 目前是規則式聚合，不是高品質人工編輯等級的摘要。
- `sync-vault` 只把產生筆記的檔案修改視為回饋；目前不是完整的 Obsidian plugin 或雙向同步引擎。
- 桌面視窗目前是本地 tkinter launcher，還不是正式 Windows 安裝包。
- 抽取品質 eval 目前是 CLI 產生 JSONL / Markdown 打分表；還沒有圖形化 eval UI。
- archive / deep archive 的預算機制還是產品方向，不是完整功能。
- 記憶圖是靜態 HTML 匯出，還不是完整 app。

## 測試

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## 專案方向

下一個重要問題不是 1B 小模型會不會摘要，而是它能不能抽出後續真的可用的結構，讓記憶圖透過使用訊號慢慢驗證：

- 摩擦結構
- 狀態機
- 決策疑問
- 品味與判斷模式
- 重複出現的技術坑

如果你拿自己的聊天紀錄測，最有價值的 issue 會是：真實的抽取雜訊、漏掉的重要 atom，或記憶圖行為不符合直覺的例子。
