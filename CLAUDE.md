# CLAUDE.md - invest-system プロジェクト

## プロジェクト概要
ミネルヴィニ流成長株投資のスクリーニング・分析ダッシュボード。
目標: 2029年末までに資産1億円 / Stage-2成長株集中投資

## サイトURL
https://invest-system-six.vercel.app/

## アーキテクチャ
```
[J-Quants API] → [run_screen_full.py] → screen_full_results.json
                  [stock_mcp_server.py] → chart/pattern/fins/timeline_data.json
                                        ↓
                  [GitHub Actions 15:05 JST] → invest-data repo (public)
                                        ↓
                  [index.html on Vercel] ← raw.githubusercontent.com から全データ取得
```

## 重要ファイル
| ファイル | 役割 |
|---------|------|
| `index.html` | サイト全体（HTML+CSS+JS一体、約900行） |
| `stock_mcp_server.py` | MCPサーバー（Claude Desktop用、40+ツール） |
| `run_screen_full.py` | 自動スクリーニング（GA + Windows TS） |
| `daily_screening.yml` | GitHub Actions ワークフロー |

## データフロー
1. `run_screen_full.py --fresh` → 全銘柄スクリーニング → `data/screen_full_results.json`
2. `stock_mcp_server.py` の export 関数群 → `chart_data.json`, `fins_data.json` 等
3. GitHub Actions が invest-data リポジトリに sync
4. サイトが `raw.githubusercontent.com` から JSON を fetch して表示

## パス設定
- **ローカル**: `C:\Users\yohei\Documents\invest-system`（デフォルト）
- **GitHub Actions**: 環境変数 `INVEST_BASE_DIR` / `INVEST_GITHUB_DIR` で上書き
- **絶対にパスを直書きしない**。必ず `os.environ.get()` でフォールバック

## やってはいけないこと
1. **JSONにNaN/Inf値を出力しない** → ブラウザのJSON.parseが壊れる。`_sanitize_nans()`を必ず通す
2. **invest-dataリポジトリをPrivateにしない** → サイトのデータ読み込みが全て停止する
3. **CDNスクリプトを追加しない** → セキュリティリスク。ライブラリはローカルファイルとして配置
4. **Windowsパスを直書きしない** → GitHub Actions（Ubuntu）で動かなくなる
5. **sessionStorageでAPIキーを保存しない** → 毎回再入力が必要になり不便
6. **Gemini APIキーをHTTPヘッダーで送らない** → CORSプリフライトで失敗する

## export対象銘柄のロジック
chart/fins/pattern/timeline データの対象:
- 監視銘柄（watchlist.json）→ 常に含む
- ポートフォリオ（portfolio.json）→ 常に含む
- 年初来高値更新圏（price >= ytd_high × 0.98）→ 自動選定
- extra_codes引数 → 手動追加

## データ整合性
- export関数は **invest-data上のresults** を参照する（ローカルとのズレ防止）
- NaN対策: `_sanitize_nans()` が numpy.float64 にも対応済み

## API
- **J-Quants V2**: 株価・業績データ（`JQUANTS_API_KEY`環境変数）
- **Gemini**: ニュース・分析・中期計画（ブラウザlocalStorage `gk`キー）
- **Claude**: 分析・判定（ブラウザlocalStorage `ck`キー）

## localStorage キー一覧
| キー | 内容 |
|------|------|
| `gk` | Gemini APIキー |
| `ck` | Claude APIキー |
| `memo_{code}` | 銘柄メモ |
| `sim_{code}` | シミュレーション設定 |
| `knowledge_{code}` | ナレッジバッファ（export_knowledgeで永続化） |
| `wl_local` | 監視銘柄（サイトから追加分） |
| `pf_local` | ポートフォリオ（サイトから追加分） |
| `pf_cash` | 資金残高 |
| `pf_history` | 売却履歴 |
| `cf_presets` | カスタムフィルタプリセット |
| `ai_hist_{code}` | AI分析履歴 |

## テスト方法
- ローカル: `python -c "import stock_mcp_server as s; print(s.export_chart_data())"`
- GA手動実行: Actions → Daily Stock Screening → Run workflow
- サイト確認: https://invest-system-six.vercel.app/ をCtrl+Shift+Rで強制リロード
