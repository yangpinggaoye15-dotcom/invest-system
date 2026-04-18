# リファクタ計画（2026-04-18 開始）

## 目的
AI 精度低下の根本原因である「ファイル巨大化」を解消し、機能別モジュールに分割する。

## 根本課題
| ファイル | 現行行数 | 目標 |
|---|---:|---|
| `stock_mcp_server.py` | ~2,500 行 | 80 行（MCP tool 登録のみ）+ `mcp_server/` 配下に分割 |
| `run_teams.py` | ~2,500 行 | 50 行（エントリポイント）+ `teams/` 配下に分割 |
| `index.html` | ~4,000 行 | 任意分割（Phase E） |

**原則**: 1 ファイル 500 行以下（md は 200 行以下）

---

## Phase A: 安全網の構築（2日）
- A-1. スモークテスト追加（主要関数の現状出力をスナップショット化）
- A-2. ヘルスチェック拡張（`run_teams.py --health` で現行動作確認）
- A-3. バックアップタグ作成（`git tag refactor-backup-YYYYMMDD`）

検証: `python run_teams.py report` がリファクタ前後で同一出力

## Phase B: run_teams.py 分割（3日）
```
run_teams.py        (50行・エントリポイント)
teams/
├─ _base.py         (call_claude, call_gemini等の共通ヘルパー)
├─ _tools.py        (_execute_tool, _agent_system_prompt)
├─ _phase.py        (detect_phase)
├─ _scenarios.py    (_generate_scenarios, _analyze_daily_deviation等)
├─ info.py / analysis.py / risk.py / strategy.py
├─ verification.py / security.py / audit.py / hr.py
└─ report.py
```
検証: スケジュールタスク（18:15〜20:10）が従来通り動く

## Phase C: stock_mcp_server.py 分割（4日）
```
stock_mcp_server.py  (80行・MCP tool 登録)
mcp_server/
├─ jquants.py / database.py / minervini.py
├─ screening.py / bulk.py / portfolio.py / watchlist.py
├─ charts.py / fins.py / equity.py
```
検証: MCP ツール呼び出しが全て従来通り動作

## Phase D: cranky-nash 業績チェック移植（1日）
- `_calc_earnings_score()` と `check_earnings` MCP ツールを新しい `mcp_server/fins.py` に手動移植
- cranky-nash worktree 削除

検証: `check_earnings 9163`（ナレルグループ）が動作

## Phase E: index.html 分割（任意・2日）
- `index.html` → entry + router（200行）
- `pages/screening.html` 他（各 500 行程度）
- CSS/JS 外出し

検証: Vercel サイトの全ページが従来通り動作

## Phase F: ROADMAP.md 分離（0.5日）
- CLAUDE.md から Phase 1/2/3 目標・KGI/KPI を削除
- `docs/ROADMAP.md` を新規作成（ユーザー用メモ）
- CLAUDE.md は実装規約のみの短いファイルへ

---

## 合計見積: 12.5 日（平日夜+土日で 2〜3 週間）

## 進捗ログ
- 2026-04-18: Phase 前準備完了（destructive simplification 破棄・worktree 整理・Doubler スクリプトコミット）
