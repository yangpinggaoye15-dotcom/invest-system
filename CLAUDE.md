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
       └── run_teams.py (Team1〜9)
             ├── Gemini API — リアルタイム情報収集
             ├── Claude API (claude-sonnet-4-6) — 分析・レポート生成
             └── reports/daily/*.md + kpi_log.json → invest-data/reports/
                          ↓
              index.html (Vercel) ← raw.githubusercontent.com
```

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

---

## テスト方法
```bash
# GitHub Actions手動実行
Actions → Daily Stock Screening → Run workflow
Actions → Daily Investment Teams → Run workflow

# サイト確認
https://invest-system-six.vercel.app/ を Ctrl+Shift+R で強制リロード
```
