# Sporepath

[English](README.md)

![一隻小小的 Sporepath scout 把 AI 對話碎片整理成專注路徑與潛在靈感孢子](assets/hero-mascot.png)

Sporepath 是一個 local-first 實驗：把你和 AI 的聊天紀錄，轉成一張會代謝的記憶圖。

它不是另一個筆記庫。它想驗證的是：過去聊天裡留下的想法碎片，能不能變成兩層有用的思考路徑：

- **專注路徑**：最近常用、常被碰到的想法會變粗，幫你延續當下正在研究的脈絡。
- **潛在路徑**：暫時用不到、低活性的想法會沉下去，不干擾你，但未來遇到新問題時可以被重新喚醒。

小型本地模型在這裡不是「真正的大腦」，而是 scout。它負責從聊天紀錄裡找出候選的 thought atoms；真正決定哪些路徑變粗、淡掉、沉入封存的，是本地規則和後續使用訊號。

## 它現在能做什麼

- 匯入 ChatGPT 風格的 `conversations.json` 和一般 JSONL 聊天紀錄。
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

它會打開一個本地小視窗，日常只需要三個動作：

- **Refresh Now**：重建 notes、匯出 Obsidian vault、更新 graph。
- **Sync Vault**：把 Obsidian 裡改過的 notes 視為使用回饋，回流加粗 source atoms。
- **Open Vault**：打開 Markdown vault 資料夾，讓 Obsidian 使用。
- **Inspire**：輸入卡住的問題，請 Codex 產生「怪但有橋」的下一手。

這個 batch launcher 預設使用 repo 裡的 `real_memory.sqlite`。視窗裡仍然可以修改 DB、聊天匯出檔、vault 和 graph 路徑。

按 **Auto-detect Sources** 可以尋找本機 Codex 和 Claude 的對話來源。Sporepath 只使用白名單中的可能對話來源：

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

小模型一定會有雜訊。它只是 scout，不是裁判。可以用 `show` 檢查它為什麼留下某個 atom：

```powershell
python -m sporepath --db qwen_trial.sqlite show <atom-id>
```

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

## 目前限制

- 目前的 edges 已經帶 shared-tag evidence 和 confidence metadata，但仍然不是真正的語意 embedding。
- `qwen3:1.7b` 可以抽出有用候選，但也會製造雜訊。
- `digest` 目前是規則式聚合，不是高品質人工編輯等級的摘要。
- `sync-vault` 只把產生筆記的檔案修改視為回饋；目前不是完整的 Obsidian plugin 或雙向同步引擎。
- 桌面視窗目前是本地 tkinter launcher，還不是正式 Windows 安裝包。
- 還沒有 eval UI，現在仍然需要用 `focus` 和 `show` 手動檢查。
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
