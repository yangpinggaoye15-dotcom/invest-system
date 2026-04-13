# CLAUDE.md - invest-system プロジェクト

## 保守ルール
**このファイルは変更のたびに更新すること。** 詳細は各ドキュメントを参照。
- 組織図・KGI/KPI体系 → `org/org_chart.md`
- PDCA運用ルール → `org/pdca_rules.md`
- 各チームマニュアル → `teams/team[1-9]_*.md`

---

## プロジェクト概要
ミネルヴィニ流成長株投資のスクリーニング・分析・自動レポートシステム。
**サイト**: https://invest-system-six.vercel.app/

| フェーズ | 期間 | 資産目標 | 移行条件（2ヶ月連続） |
|---------|------|---------|-------------------|
| Phase 1 | 〜2026Q2 | 200万→300万 | 勝率50%・PF2.0・DD10%以内 |
| Phase 2 | 〜2026Q4 | 300万→600万 | 勝率55%・PF2.5・DD8%以内 |
| Phase 3 | 〜2027Q2 | 600万→1,200万 | 勝率60%・PF3.0・DD6%以内 |

---

## アーキテクチャ

```
[J-Quants API] → run_screen_full.py → screen_full_results.json
                  stock_mcp_server.py → chart/fins/pattern/timeline_data.json
                          ↓
     [GitHub Actions 15:05 JST] daily_screening.yml → invest-data repo (public)
     [GitHub Actions 16:35 JST] daily_teams.yml
       └── run_teams.py (Team1〜9) ← v2: マルチエージェントアーキテクチャ
             │
             ├── _run_agent_team() ─ エージェントループ（Claude API Tool Use）
             │     ├── search_market_info → Gemini Google Search
             │     ├── get_screening_data → screen_full_results.json
             │     ├── get_fins_data → fins_data.json
             │     ├── read_past_report → 他チームレポート参照
             │     ├── get_simulation_status → simulation_log.json
             │     ├── get_kpi_history → kpi_log.json
             │     ├── read_knowledge / write_knowledge → knowledge/ フォルダ
             │     └── finalize_report → レポート確定・保存
             │
             ├── Claude API (claude-sonnet-4-6) — ツール呼び出し + 分析
             ├── Gemini API — Google Search grounding（search_market_infoツール経由）
             └── reports/daily/*.md + knowledge/*.md → invest-data/reports/
                          ↓
              index.html (Vercel) ← raw.githubusercontent.com
```

### エージェントアーキテクチャの特徴
- **自律的ツール選択**: 各チームエージェントが必要なデータを自律的に決定・取得
- **知識蓄積ループ**: `knowledge/` フォルダに過去の洞察を保存 → 次回実行時に参照して継続学習
- **非決定論的実行**: 毎回Claudeが最適なツール呼び出し順序を自律判断
- **継続的改善**: read_knowledge → 分析 → write_knowledge のサイクルで精度向上

### knowledge/ フォルダ（自律学習DB）
| ファイル | 用途 |
|---------|------|
| `info_patterns.md` | 情報収集チームの発見・収集パターン |
| `analysis_patterns.md` | 分析チームの有効パターン・的中傾向 |
| `risk_patterns.md` | リスク管理チームの発見 |
| `strategy_patterns.md` | フェーズ判定精度・有効戦略 |
| `report_patterns.md` | 統合レポートの改善点 |
| `security_patterns.md` | セキュリティ脅威情報 |
| `audit_patterns.md` | KPIトレンド・改善サイクル |
| `hr_patterns.md` | チームパフォーマンストレンド |
| `verification_patterns.md` | シミュレーション検証パターン |
| `fix_patterns.md` | 欠陥修正履歴・修正判断基準 |
| `event_patterns.md` | イベント管理ルール・命名規則 |

---

## コアファイル構成

| ファイル | 役割 |
|---------|------|
| `index.html` | サイト全体（HTML+CSS+JS一体、~4000行） |
| `run_teams.py` | 9チーム自動実行スクリプト |
| `run_screen_full.py` | 自動スクリーニング |
| `stock_mcp_server.py` | MCPサーバー（Claude Desktop用） |
| `api/claude.js` | Claude APIプロキシ |
| `api/gemini.js` | Gemini APIプロキシ |
| `teams/team[1-9]_*.md` | 各チームマニュアル |
| `org/org_chart.md` | 組織図・責任マトリクス・KGI/KPI体系 |
| `org/pdca_rules.md` | PDCA運用ルール・shared_context仕様 |

### レポートファイル（`reports/daily/`）
| ファイル | 担当チーム |
|---------|---------|
| `info_gathering.md` | Team1 情報収集 |
| `analysis.md` | Team2 銘柄選定・仮説 |
| `risk.md` | Team3 リスク管理 |
| `strategy.md` | Team4 投資戦略 |
| `internal_audit.md` | Team5 内部監査 |
| `security.md` | Team6 セキュリティ |
| `latest_report.md` | Team7 レポート統括 |
| `verification.md` | Team8 検証 |
| `hr_report.md` | Team9 人事（週次） |
| `simulation_log.json` | Team8管理（最大5銘柄追跡） |
| `kpi_log.json` | 全チームKPIスコア履歴（直近3年） |
| `shared_context.md` | 全チーム共有情報ハブ |
| `daily_context.json` | データ準備スクリプト生成（全チームの入力元） |
| `fix_report.md` | Team Fix 欠陥修正レポート |
| `events_report.md` | イベント管理チーム週次レポート |

---

## シミュレーション仕様
- **追跡**: 最大5銘柄同時、10営業日、score≥6・rs_26w上位から選定
- **終了条件**: 損切り(-8%) / 目標①(+25%) / 10営業日経過
- **翌日仮説**: `next_hypothesis`フィールド（方向・根拠・確信度・注目価格）
- **差異分析**: 翌営業日に検証 → `hypothesis_history`に蓄積

---

## API・認証

| Secret/変数 | 用途 |
|------------|------|
| `ANTHROPIC_API_KEY` | Claude API（Actions + Vercel） |
| `GEMINI_API` | Gemini API（Actions + Vercel） |
| `JQUANTS_API_KEY` | J-Quants V2 株価データ |
| `DATA_REPO_TOKEN` | invest-data リポジトリへのpush権限 |

---

## サイト運営の責任部署
**Team 6 セキュリティチーム（主担当）/ Team 5 内部監査（評価）**
詳細は `org/org_chart.md` の「サイト運営監視」を参照。
- GitHub Actions 実行時間が3分未満 → Claude APIクレジット不足を疑い即確認
- KPIタブ全部"-" → `kpi_log.json` のフォーマット不整合を疑う

---

## やってはいけないこと

1. **JSONにNaN/Inf値を出力しない** → `_sanitize_nans()` を必ず通す
2. **invest-dataリポジトリをPrivateにしない** → データ読み込み全停止
3. **CDNスクリプトを追加しない** → セキュリティリスク
4. **Windowsパスを直書きしない** → `os.environ.get()` でフォールバック
5. **APIキーをlocalStorageに保存しない** → `/api/` proxy経由で使う
6. **[事実]と[AI分析]を混在させない** → ラベルを必ず付ける
7. **投資判断を自動実行しない** → シミュレーションのみ、最終判断はオーナー
8. **各mdファイルを200行超にしない** → AIの精度低下防止
9. **`run_teams.py` の kpi_log.json 出力はキーを英語・値を数値にすること** → `index.html` は英語キー（`info`, `analysis`等）+ 数値（10点換算）を期待
10. **`score`・`rs_26w` が null の銘柄に対し `or 0` でフォールバックすること** → Python の None との比較/フォーマットでTypeError発生を防ぐ
11. **`screen_full_results.json` はdict形式（コードをキー）** → `isinstance(screen, list)` では常に空になる。`screen_to_list()` を使うこと
12. **`run_screen_full.py` の PARALLEL_WORKERS は3以下にすること** → 15だとJ-Quants 429エラーで98.9%失敗する
13. **スクリーニングは `--bulk` / `--bulk-update` モードを推奨** → per-stockモードの約200分の1のAPIコール数。`daily_screening.yml` はbulkモードを使用中

---

## テスト方法
```bash
# GitHub Actions手動実行
Actions → Daily Stock Screening → Run workflow
Actions → Daily Investment Teams → Run workflow

# ローカルでbulkモードのテスト（環境変数を設定してから）
python run_screen_full.py --bulk         # 全銘柄（~15分）
python run_screen_full.py --bulk-update  # 差分更新（~1分）
python run_screen_full.py --test         # 先頭20銘柄（動作確認用）

# サイト確認
https://invest-system-six.vercel.app/ を Ctrl+Shift+R で強制リロード
```
