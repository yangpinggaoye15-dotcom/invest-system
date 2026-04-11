# FILE_INVENTORY.md
# ファイル一覧・目的・変更ログ

このファイルはプロジェクト内の全ファイルの目的を記録します。
ファイルを追加・削除・移動した際は必ずこのファイルも更新すること。

---

## ルートディレクトリ（現役ファイル）

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `index.html` | サイト全体 HTML+CSS+JS（約4000行）。チャート・スクリーニング・レポート・KPIダッシュボードを全て含む | 現役 |
| `stock_mcp_server.py` | MCPサーバー（Claude Desktop連携用）。42+ツール。chart/fins/pattern/timeline データのexportも担当 | 現役 |
| `run_screen_full.py` | 全銘柄スクリーニング。J-Quants APIから株価取得→ミネルヴィニ7条件判定→screen_full_results.json出力 | 現役 |
| `run_teams.py` | 8チーム投資自動分析。Gemini（情報収集）+ Claude（構造化分析）→ レポートMD + kpi_log.json + simulation_log.json | 現役 |
| `CLAUDE.md` | プロジェクト保守ルール・アーキテクチャ全体図。変更のたびに更新必須 | 現役 |
| `FILE_INVENTORY.md` | 本ファイル。全ファイルの目的・変更ログ | 現役 |
| `README.md` | GitHubリポジトリ概要 | 現役 |
| `requirements.txt` | Python依存パッケージ（requests, pandas, plotly, mcp, yfinance） | 現役 |
| `lightweight-charts.js` | TradingView製チャートライブラリ（CDN不使用のためローカル配置） | 現役 |
| `manifest.json` | PWA設定（アプリアイコン・名前等） | 現役 |
| `sw.js` | Service Worker（PWAキャッシュ制御） | 現役 |
| `_routes.json` | Vercel routing設定 | 現役 |
| `watchlist.json` | 監視銘柄リスト（stock_mcp_server.py経由で管理） | 現役 |
| `portfolio.json` | ポートフォリオ（stock_mcp_server.py経由で管理） | 現役 |
| `chart_data.json` | export_chart_data()が生成。チャートページ用OHLCV+指標データ | 自動生成（現役） |
| `fins_data.json` | export_fins_data()が生成。財務データ | 自動生成（現役） |
| `pattern_data.json` | export_pattern_data()が生成。パターン検出結果 | 自動生成（現役） |
| `timeline_data.json` | export_timeline_data()が生成。タイムラインデータ | 自動生成（現役） |
| `sync_local.py` | GitHubから最新データをローカルに同期。タスクスケジューラで毎日19:00実行。invest-system-github + invest-data の git pull + データ品質チェック | 現役 |
| `check_health.py` | GitHub Actions完了後のヘルスチェック。データ整合性検証 | 現役（手動実行） |
| `wrangler.toml` | Cloudflare Workers設定（現在はVercel使用のため未使用。削除候補） | 要確認 |

---

## api/ ディレクトリ

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `api/claude.js` | Claude APIプロキシ（Vercel Serverless Function）。ANTHROPIC_API_KEY環境変数使用 | 現役 |
| `api/gemini.js` | Gemini APIプロキシ（Vercel Serverless Function）。GEMINI_API環境変数使用 | 現役 |

---

## scripts/ ディレクトリ

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `scripts/run_daily_screening.ps1` | **メイン実行スクリプト**。タスクスケジューラで毎日15:00 JST実行。screen_full → entry_screen_v3 → invest-data push | 現役 |
| `scripts/run_daily_teams.ps1` | タスクスケジューラで毎日16:35 JST実行。run_teams.py（8チームレポート）を実行 | 現役 |
| `scripts/setup_scheduler.ps1` | Windowsタスクスケジューラに run_daily_screening + run_daily_teams を登録するセットアップスクリプト | 現役（初回のみ） |
| `scripts/setup_power.ps1` | 電源設定（スリープ回避）セットアップ | 現役（初回のみ） |
| `scripts/run_cycle.ps1` | screening + teams を一度に実行するサイクルスクリプト。現在は分離されているため使用頻度低 | 要確認 |

---

## .github/workflows/ ディレクトリ

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `daily_screening.yml` | バックアップ用GitHub Actions。ローカル実行が失敗した場合の手動実行用。自動スケジュールは無効化済み | 現役（バックアップ） |
| `daily_teams.yml` | 8チームレポート生成 GitHub Actions。毎日16:35 JST自動実行（cron `35 7 * * *`） | 現役 |
| `health_check.yml` | システム正常性チェック | 現役 |

---

## reports/ ディレクトリ（現役）

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `reports/entry_screen_v3.py` | **最終エントリーフィルター**（現役）。SQLite直読みで全銘柄スクリーニング（API不要・約1秒）。7/7 + gap 0〜5% + OBV15日<1.0 + RS50w>1.3 | 現役 |
| `reports/false_bo_v3.py` | フォルスブレイクアウト分析v3（現役）。TARGET_HIT(+20%) vs STOP_LOSS(-7%)判定 | 現役 |
| `reports/false_bo_v3_results.json` | false_bo_v3.py の分析結果（銘柄別勝敗データ） | 自動生成（現役） |
| `reports/obv_window_optimize.py` | OBVウィンドウ最適化スクリプト。[5,10,15,20,30,40日]でHit率比較。結論: 15日が最良 | 研究用（保存） |
| `reports/obv_window_detail.py` | OBV閾値別Hit率カーブ・複合効果分析。gap×OBV複合で79.2%Hit率 | 研究用（保存） |
| `reports/obv_window_result.txt` | obv_window_optimize.py の結果テキスト | 研究用（保存） |
| `reports/obv_window_detail.txt` | obv_window_detail.py の結果テキスト | 研究用（保存） |
| `reports/entry_screen_result.json` | entry_screen_v3.py の出力（JSON形式）。サイト表示・invest-dataにsync | 自動生成（現役） |
| `reports/entry_screen_result.txt` | entry_screen_v3.py の出力（テキスト形式）。人間が読むログ | 自動生成（現役） |
| `reports/10y_analysis.json` | 10年分析結果 | 要確認 |
| `reports/5y_winners.csv` | 5年パフォーマンス上位銘柄リスト（find_5y_winners.pyが生成） | 要確認 |
| `reports/unicorn_analysis.json` | ユニコーン銘柄分析結果 | 要確認 |
| `reports/audit_log.md` | 監査ログ | 現役 |
| `reports/daily/` | 8チームの日次レポートMD・kpi_log.json・simulation_log.json | 現役 |

---

## data/ ディレクトリ

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `data/stock_prices.db` | **メインDB**。全銘柄の日次株価（SQLite）。run_screen_full.pyが書き込み | 現役（重要） |
| `data/fins_data.db` | 財務データDB（SQLite） | 現役 |
| `data/equity_master_cache.json` | 銘柄マスター情報キャッシュ（J-Quants APIから取得） | 現役 |
| `data/screen_full_results.json` | スクリーニング結果。全銘柄の7条件判定結果。Vercel/invest-dataに配信 | 自動生成（現役） |
| `data/screen_full_progress.json` | スクリーニング進捗状態 | 自動生成（現役） |
| `data/screen_full.log` | スクリーニング実行ログ | 自動生成（現役） |
| `data/pattern_results.json` | パターン検出結果キャッシュ | 自動生成（現役） |
| `data/portfolio.json` | ポートフォリオデータ（data/配下のもの） | 現役 |
| `data/ytd_high_apr3.py` | 年初来高値計算スクリプト（一時的なデータ修正用）| 要確認 |
| `data/ytd_err.txt` | ytd_high_apr3.py のエラーログ | 要確認（削除候補） |
| `data/ytd_out.txt` | ytd_high_apr3.py の出力ログ | 要確認（削除候補） |

---

## knowledge/ ディレクトリ

| 目的・用途 | 状態 |
|----------|------|
| MCPツールの `save_knowledge` / `export_knowledge` で保存した銘柄分析メモ。`stock_mcp_server.py` の `export_site_data()` がここを読んでサイトに表示する機能あり | 現役（要確認） |

---

## teams/ ディレクトリ

| ファイル | 目的・用途 | 状態 |
|---------|----------|------|
| `teams/t1_*.md` | Team 1（情報収集）のプロンプトテンプレート | 現役 |
| `teams/t2_*.md` | Team 2（分析）のプロンプトテンプレート | 現役 |
| `teams/t3_*.md` | Team 3（リスク管理）のプロンプトテンプレート | 現役 |
| `teams/t4_*.md` | Team 4（投資戦略）のプロンプトテンプレート | 現役 |
| `teams/t5_*.md` | Team 5（内部監査/フォローアップ）のプロンプトテンプレート | 現役 |
| `teams/org_chart.md` | 組織図 | 現役 |
| `teams/pdca_rules.md` | PDCAルール | 現役 |
| `teams/0000.json` | チーム設定JSON | 現役 |
| `teams/5816.json` | 銘柄5816の設定/ナレッジ | 要確認 |

---

## org/ ディレクトリ

| 目的・用途 | 状態 |
|----------|------|
| 組織・戦略関連ドキュメント | 要確認 |

---

## csv_output/ ディレクトリ

| 目的・用途 | 状態 |
|----------|------|
| `stock_mcp_server.py` のexport関数群が中間データとしてCSVを生成していた名残り。現在はJSONに移行済みで実質不要。GitHub Actionsのキャッシュキーとして参照されているが機能的には空でよい | 要確認（削除候補） |

---

## logs/ ディレクトリ

| 目的・用途 | 状態 |
|----------|------|
| `run_daily_screening.ps1` が生成するログファイル（`screening_YYYYMMDD_HHmm.log`） | 自動生成（現役） |

---

## _archive/ ディレクトリ（アーカイブ済み・使用しない）

### _archive/fujikura_research/
フジクラ(5803)を手動調査した際の一時ファイル群。

| ファイル | 元の目的 |
|---------|---------|
| `5803_chart_weekly.json` | フジクラ週次チャートデータ（一時取得） |
| `5803_daily_full.json` | フジクラ日次全データ（一時取得） |
| `fujikura_chart.json` | フジクラチャートデータ（整形版） |
| `fujikura_weekly_chart.html` | フジクラ週次チャートHTML（ブラウザ確認用） |

### _archive/temp_scripts/
一時的に作成したスクリプト群。

| ファイル | 元の目的 |
|---------|---------|
| `analyze_now.py` | その場での銘柄分析用（一時スクリプト） |
| `run_teams_now.py` | チームを即座に実行するショートカット |
| `show_fins.py` | 財務データをターミナルに表示（確認用） |
| `test_quick.py` | 各種機能のクイックテスト |
| `find_5y_winners.py` | 5年間のパフォーマンス上位銘柄を探すスクリプト |

### _archive/old_db/
ルート直下に誤配置・または空だったDB。正規のDBは `data/` 配下にある。

| ファイル | 元の目的 |
|---------|---------|
| `stock_data.db` | 旧DB（空ファイル） |
| `stock_prices.db` | 旧DB（空ファイル、data/配下のものが正） |

### _archive/monitor_system/
価格アラート・銘柄監視システムを作ろうとしていた痕跡。タスクスケジューラで定期実行しSlack/メール通知する想定だったが未完成・未使用。

| ファイル | 元の目的 |
|---------|---------|
| `monitor_stocks.py` | 価格監視メインスクリプト |
| `monitor_config.json` | 監視対象銘柄・閾値設定 |
| `monitor_log.txt` | 実行ログ |
| `.env.monitor` | 通知先（Slack webhook等）の環境変数 |

### _archive/reports_old/
スクリーニング・分析スクリプトの旧バージョン群。現役は `reports/entry_screen_v3.py` と `reports/false_bo_v3.py`。

| ファイル | 元の目的 |
|---------|---------|
| `false_bo_analysis.py` | フォルスブレイクアウト分析 v1 |
| `false_bo_results.json` | v1 の結果 |
| `false_bo_v2.py` | v2（改善版） |
| `false_bo_v2_results.json` | v2 の結果 |
| `entry_filter_screen.py` | エントリーフィルター初期版 |
| `entry_screen_v2.py` | エントリーフィルター v2 |
| `entry_screen_v2_result.txt` | v2 の結果テキスト |
| `entry_screen_v3_result.txt` | v3の重複出力（entry_screen_result.txtが正） |
| `5y_winners_err.txt` | find_5y_winners.py のエラーログ |
| `5y_winners_log.txt` | find_5y_winners.py の実行ログ |

### _archive/charts/
lightweight-chartsで一時生成したHTMLチャートファイル群。ブラウザでの確認用。

| ファイル | 元の目的 |
|---------|---------|
| `*.html` | 個別銘柄チャートHTML（ブラウザ確認用一時ファイル） |
| `*_daily.csv` | 日次データCSV（チャート生成用中間ファイル） |

### _archive/test_scripts/
シミュレーション機能のユニットテスト・統合テスト。シミュレーション機能が安定した時点で役割を終えた。

| ファイル | 元の目的 |
|---------|---------|
| `test_sim_integration.py` | run_teams.pyのシミュレーション関数の統合テスト（APIモック使用） |
| `test_sim_v2.py` | シミュレーションv2のユニットテスト |

---

## 変更ログ

| 日付 | 変更内容 | 担当 |
|------|---------|------|
| 2026-04-11 | `_archive/` フォルダ作成。不要ファイル群を各サブフォルダに移動（fujikura_research・temp_scripts・old_db・monitor_system・reports_old・test_scripts・charts） | Claude |
| 2026-04-11 | `FILE_INVENTORY.md` 新規作成。全ファイルの目的・状態を記録開始 | Claude |
| 2026-04-11 | `reports/entry_screen_v3.py` 新規作成。最終エントリーフィルター（SQLite直読み・API不要） | Claude |
| 2026-04-11 | `scripts/run_daily_screening.ps1` に entry_screen_v3.py 実行ステップを追加 | Claude |
| 2026-04-11 | `.github/workflows/daily_screening.yml` に entry_screen_v3.py ステップ + entry_screen_result.json のsync追加 | Claude |
| 2026-04-08 | `reports/obv_window_optimize.py` `reports/obv_window_detail.py` 作成。OBVウィンドウ最適化（結論: 15日が最良） | Claude |
