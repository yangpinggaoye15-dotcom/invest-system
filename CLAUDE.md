# CLAUDE.md - invest-system プロジェクト

## 保守ルール
**重要: このファイルは変更のたびに更新すること。** コードやアーキテクチャに変更を加えた場合は、このCLAUDE.mdも同時に更新してコミットする。

---

## プロジェクト概要
ミネルヴィニ流成長株投資のスクリーニング・分析・自動レポートシステム。

**投資目標（3年ロードマップ）**
| フェーズ | 期間 | 資産目標 | 月次リターン |
|---------|------|---------|------------|
| Phase 1 | 〜2026Q2 | 200万→300万 | +33万円/月 |
| Phase 2 | 〜2026Q4 | 300万→600万 | +75万円/月 |
| Phase 3 | 〜2027Q2 | 600万→1,200万 | +150万円/月 |
| 2年目   | 〜2027末 | 1,200万→2,000万 | — |
| 3年目   | 〜2028末 | 2,000万→1億円  | — |

フェーズ移行条件: 勝率50%以上・PF2.0以上・DD10%以内を**2ヶ月連続**で達成

## サイトURL
https://invest-system-six.vercel.app/

---

## アーキテクチャ全体図

```
[J-Quants API]  →  run_screen_full.py  →  screen_full_results.json
                   stock_mcp_server.py  →  chart/fins/pattern/timeline_data.json
                                  ↓
        [GitHub Actions 15:05 JST] daily_screening.yml
                                  ↓
              invest-data repo (public / yangpinggaoye15-dotcom)
                                  ↓
              index.html (Vercel)  ←  raw.githubusercontent.com

[GitHub Actions 毎日 16:35 JST] daily_teams.yml
  └── run_teams.py (8チーム)
        ├── Gemini API (Google Search grounding) — リアルタイム情報収集
        ├── Claude API (claude-sonnet-4-6) — 構造化分析
        └── reports/daily/*.md + kpi_log.json → invest-data/reports/
```

---

## ファイル構成

### コアファイル
| ファイル | 役割 |
|---------|------|
| `index.html` | サイト全体（HTML+CSS+JS一体、~4000行） |
| `stock_mcp_server.py` | MCPサーバー（Claude Desktop用、40+ツール） |
| `run_screen_full.py` | 自動スクリーニング（GitHub Actions + ローカル） |
| `run_teams.py` | 8チーム投資チーム自動実行スクリプト |

### API（Vercel Serverless Functions）
| ファイル | 役割 |
|---------|------|
| `api/claude.js` | Claude APIプロキシ（`ANTHROPIC_API_KEY`環境変数） |
| `api/gemini.js` | Gemini APIプロキシ（`GEMINI_API`環境変数） |

### ワークフロー
| ファイル | スケジュール | 役割 |
|---------|------------|------|
| `.github/workflows/daily_screening.yml` | 毎平日 15:05 JST | スクリーニング → invest-data sync |
| `.github/workflows/daily_teams.yml` | 毎日 16:35 JST（cron `35 7 * * *`） | 8チームレポート生成 |

### レポート（`reports/daily/`）
| ファイル | チーム |
|---------|------|
| `info_gathering.md` | 情報収集チーム（Team 1） |
| `analysis.md` | 分析チーム（Team 2） |
| `risk.md` | リスク管理チーム（Team 3） |
| `strategy.md` | 投資戦略チーム（Team 4） |
| `internal_audit.md` | 内部監査チーム（Team 5） |
| `security.md` | セキュリティチーム（Team 6） |
| `report.md` | レポート統括（Team 7） |
| `verification.md` | 検証チーム（Team 8） |
| `YYYY-MM-DD_daily_report.md` | 日付付き統合レポート |
| `latest_report.md` | 最新版（サイト表示用） |
| `source_log.md` | 情報源・信頼度ログ（レポートには非掲載） |
| `simulation_log.json` | シミュレーション追跡ログ（アクティブ + 履歴） |
| `kpi_log.json` | チームKPIスコア履歴（直近3年分・1095エントリ保持） |

### 生成JSONファイル（ルート）
| ファイル | 生成元 |
|---------|------|
| `chart_data.json` | `stock_mcp_server.py export_chart_data()` |
| `fins_data.json` | `stock_mcp_server.py export_fins_data()` |
| `pattern_data.json` | `stock_mcp_server.py export_pattern_data()` |
| `timeline_data.json` | `stock_mcp_server.py export_timeline_data()` |

---

## 責任分担マトリクス

各オペレーションの担当チームを明示する。新機能追加時もこの表を更新すること。

| オペレーション | 主担当 | 副担当（レビュー） | 出力先 |
|--------------|--------|-----------------|--------|
| 市場情報・ニュース収集 | Team 1 情報収集 | — | analysis.md への入力 |
| テクニカル分析・パターン検出 | Team 2 分析 | — | strategy.md への入力 |
| ファンダメンタル分析 | Team 2 分析 | — | strategy.md への入力 |
| **シミュレーション候補選定** | **Team 2 分析（テクニカル担当）** | Team 4 投資戦略 | simulation_log.json |
| **翌日仮説立案** | **Team 2 分析（テクニカル担当）** | — | simulation_log.json[next_hypothesis] |
| ポジションサイジング・損切り設計 | Team 3 リスク管理 | Team 4 投資戦略 | strategy.md |
| 市場フェーズ判定（detect_phase） | Team 4 投資戦略 | — | strategy.md |
| エントリー戦略・エグジット設計 | Team 4 投資戦略 | Team 3 リスク管理 | strategy.md |
| 全チームKPI評価・改善提案 | Team 5 内部監査 | — | internal_audit.md |
| コード監査・セキュリティチェック | Team 6 セキュリティ | — | security.md |
| 日次統合レポート生成 | Team 7 レポート統括 | — | latest_report.md |
| **シミュレーション日次追跡** | **Team 8 検証** | — | simulation_log.json |
| **仮説 vs 実勢 差異分析** | **Team 8 検証** | Team 2 分析 | verification.md |
| KPIスコア記録（kpi_log.json） | Team 8 検証 | Team 5 内部監査 | kpi_log.json |
| シミュレーション結果フィードバック | Team 8 検証 → Team 2/4 | — | verification.md |

### 追加専門家の基準
- 既存8チームで対応できない専門領域が発生した場合のみ追加を検討
- 現状の追加候補（発動条件）:
  - **マクロ経済スペシャリスト**: 地政学リスクが月3回以上市場影響した場合 → Team 1に統合
  - **オプション戦略担当**: ヘッジ需要が発生した場合（Phase 2以降）

---

## 投資チーム構成

### 組織図（8チーム）
```
オーナー（最終意思決定）
  └── 統括マネージャー（意思決定以外すべて）
        ├── 情報収集チーム（米国市場担当 / 日本市場担当 / マクロ地政学担当）
        ├── 分析チーム（テクニカル担当 / ファンダメンタル担当 / パターン検出担当）
        ├── リスク管理チーム（ポジション管理担当 / 市場リスク担当 / DD管理担当）
        ├── 投資戦略チーム（市場フェーズ判定担当 / エントリー設計担当 / エグジット戦略担当）
        ├── 内部監査チーム（全チームKPI評価 / 改善提案）
        ├── セキュリティチーム（コード監査 / 脅威情報収集）
        ├── レポート統括（日次統合レポート生成）
        └── 検証チーム（シミュレーション自動追跡 / 差異分析 / KPIフィードバック）
```

### 情報伝達フロー
```
情報収集 → 分析 → リスク管理 → 投資戦略 → レポート統括
  ↑                                              ↓
  └─────────────── 検証チームフィードバック ←────┘
                   内部監査 → 全チームへ
```

### 各チームのAPI利用
- **Gemini** (Google Search grounding): リアルタイム市場情報・ニュース収集
- **Claude** (claude-sonnet-4-6): 構造化分析・判断・レポート生成
- すべてのレポートは `[事実]` / `[AI分析]` ラベルで明示

### DAY_MODE（曜日別動作）
- **平日 (weekday)**: 市場データ取得・スクリーニング結果分析・当日戦略
- **土曜 (saturday)**: 週次振り返り・パフォーマンスレビュー・来週準備
- **日曜 (sunday)**: 翌週戦略準備・マクロ環境整理・ポートフォリオ調整計画
- 市場データ取得（J-Quants）は**平日のみ**。週末はニュース・分析・振り返りに注力

---

## KPI（Phase 1 基準 / 運用資産200万円）

### チーム全体
| KPI | 目標 | 具体額 |
|-----|------|-------|
| 月次損益 | +16.7% | +33万円/月 |
| 勝率 | 50%以上 | 2回に1回利確 |
| プロフィットファクター | 2.0以上 | — |
| 最大ドローダウン | -10%以内 | -20万円が上限 |
| 平均RR比 | 3.0以上 | 利益+9万 vs 損失-3万 |

### kpi_log.json フォーマット
```json
[
  {
    "date": "2026-03-29",
    "phase": "Attack",
    "teams": {
      "info": {"timeliness": 8, "accuracy": 7, "coverage": 8, "actionability": 7, "consistency": 8, "improvement": 7},
      "analysis": {...},
      ...
    }
  }
]
```
- 直近**3年分（1095エントリ）**を保持 → 3年ロードマップ全体を記録
- `reports/daily/kpi_log.json` → `invest-data/reports/kpi_log.json` にsync

---

## シミュレーションシステム

### 概要
- **対象**: Aランク銘柄（RS26w上位）から最も買いに近い1銘柄を毎日自動選定
- **追跡期間**: 2週間（10営業日）
- **終了条件**: 損切り到達 / 目標①到達 / 10営業日経過 のいずれか早い方

### simulation_log.json フォーマット
```json
{
  "tracking_rule": "2週間(10営業日)追跡・最大3銘柄同時",
  "actives": [
    {
      "code": "1234",
      "name": "銘柄名",
      "entry_price": 1000,
      "stop_loss": 950,
      "target1": 1100,
      "rr_ratio": 3.1,
      "start_date": "2026-03-29",
      "days_elapsed": 3,
      "current_price": 1050,
      "current_pct": 5.0,
      "result": null
    }
  ],
  "history": [...]
}
```
- **最大5銘柄同時追跡**（`MAX_SIM_SLOTS = 5`）
- **担当**: Team 8 検証（追跡） / Team 2 分析（候補選定・仮説立案）
- `run_verification()` (Team 8) が毎日自動更新
- 終了後は即座に次の候補を選定（直近30日以内に追跡した銘柄を除外）
- 旧フォーマット（`active`単体）から自動移行
- **翌日仮説**: `next_hypothesis` フィールドに方向・根拠・確信度・注目価格水準を記録
- **差異分析**: 翌営業日に実勢と比較し `hypothesis_history` に蓄積（的中率KPI化）

### detect_phase() — 市場フェーズ自動判定
```python
# returns {'phase': 'Attack'|'Steady'|'Defend', 'score': int, 'reasons': list}
# Attack: RS>1.5の銘柄比率 > 30% かつ score-7銘柄 > 5 かつ avgRS > 1.0
# Defend: RS>1.5比率 < 15% または avgRS < 0.8
# Steady: それ以外
```
- ルールベースで毎日計算（AIに左右されない一貫性）
- 投資戦略チームはこれを参考値として受け取り、最終判断を行う

---

## サイト機能

### KPIダッシュボード（`page-kpi`）
- **フェーズバッジ**: Attack / Steady / Defend を色付きで表示
- **シミュレーション追跡カード**: 現在の模擬取引状況（損益%・進捗バー）
- **チームスコア履歴**: 直近14日のスコアをチーム別に表示
- **Phase 1 目標**: 月次損益・勝率・PF・DDの達成状況
- データ元: `invest-data/reports/simulation_log.json` + `kpi_log.json`

### シミュレーションタブ（`page-simulation`）
- **アクティブカード**: 最大3銘柄を同時表示（損益%・進捗バー・損切り/目標ライン）
- **履歴テーブル**: 全追跡結果（結果バッジ: 損切り/目標①/期間終了）
- データ元: `invest-data/reports/simulation_log.json`

### レポートタブ（`page-report`）
- **チームタブ**: 統合/情報収集/分析/リスク/戦略/監査/セキュリティ/統括/検証の9タブ
- **日付ナビ**: 直近14日分のボタンで日付別統合レポートに遷移
- **Markdownレンダリング**: 見出し/テーブル/太字/`[事実]`/`[AI分析]`ラベルをHTML変換
- データ元: `invest-data/reports/*.md` + `reports/daily/YYYY-MM-DD_daily_report.md`

### モバイル最適化（≤480px）
- メトリクスグリッド: 4列→2列
- シミュレーションカード: 1列表示
- チャート高さ縮小・フィルターパネルコンパクト化

---

## データフロー詳細
1. `run_screen_full.py --fresh` → 全銘柄スクリーニング → `data/screen_full_results.json`
2. `stock_mcp_server.py` の export 関数群 → `chart_data.json` 等（ルートに生成）
3. `daily_screening.yml` → invest-data リポジトリに sync
4. `daily_teams.yml` → Gemini+Claude で8チームレポート → invest-data/reports/ に sync
5. `index.html` → `raw.githubusercontent.com` から JSON・MD を fetch して表示

---

## パス設定
- **ローカル**: `C:\Users\yohei\Documents\invest-system`（デフォルト）
- **GitHub Actions**: 環境変数 `INVEST_BASE_DIR` / `INVEST_GITHUB_DIR` / `INVEST_DATA_DIR` で上書き
- **絶対にパスを直書きしない** → 必ず `os.environ.get()` でフォールバック

---

## API・認証

### GitHub Secrets（GitHub Actions用）
| Secret | 用途 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude API |
| `GEMINI_API` | Gemini API (Google Search grounding含む) |
| `JQUANTS_API_KEY` | J-Quants V2 株価・業績データ |
| `DATA_REPO_TOKEN` | invest-data リポジトリへのpush権限 |

### Vercel環境変数（サイトAPI proxy用）
| 変数 | 用途 |
|------|------|
| `ANTHROPIC_API_KEY` | `/api/claude` proxy |
| `GEMINI_API` | `/api/gemini` proxy |

### localStorage（サイト内ユーザーデータ）
| キー | 内容 |
|------|------|
| `memo_{code}` | 銘柄メモ |
| `sim_{code}` | シミュレーション設定 |
| `knowledge_{code}` | ナレッジバッファ |
| `wl_local` | 監視銘柄（サイトから追加分） |
| `pf_local` | ポートフォリオ（サイトから追加分） |
| `pf_cash` | 資金残高 |
| `pf_history` | 売却履歴 |
| `cf_presets` | カスタムフィルタプリセット |
| `ai_hist_{code}` | AI分析履歴 |

---

## やってはいけないこと

1. **JSONにNaN/Inf値を出力しない** → `_sanitize_nans()` を必ず通す
2. **invest-dataリポジトリをPrivateにしない** → サイトのデータ読み込みが全停止
3. **CDNスクリプトを追加しない** → セキュリティリスク。ライブラリはローカルファイルとして配置
4. **Windowsパスを直書きしない** → GitHub Actions（Ubuntu）で動かなくなる
5. **APIキーをlocalStorageに保存しない** → Vercel環境変数 + `/api/` proxyを使う
6. **Gemini APIキーをHTTPヘッダーで送らない** → CORSプリフライトで失敗
7. **レポートに事実とAI分析を混在させない** → `[事実]` / `[AI分析]` ラベルを必ず付ける
8. **投資判断を自動実行しない** → シミュレーションのみ。最終意思決定はオーナー

---

## export対象銘柄のロジック
chart/fins/pattern/timeline データの対象:
- 監視銘柄（watchlist.json）→ 常に含む
- ポートフォリオ（portfolio.json）→ 常に含む
- 年初来高値更新圏（price >= ytd_high × 0.98）→ 自動選定
- extra_codes引数 → 手動追加

---

## テスト方法
```bash
# ローカルでexport関数テスト
python -c "import stock_mcp_server as s; print(s.export_chart_data())"

# GitHub Actions手動実行
Actions → Daily Stock Screening → Run workflow
Actions → Daily Investment Teams → Run workflow

# サイト確認
https://invest-system-six.vercel.app/ を Ctrl+Shift+R で強制リロード
```
