# 欠陥修正チーム ナレッジベース

## 修正判断基準
- 設定値（タイムアウト秒数・リトライ回数・MAX値）→ 修正OK
- JSONデータの数値不整合 → 修正OK（simulation_log.json等）
- knowledgeファイルの誤記・重複 → 修正OK
- index.html・api/・.github/workflows/ → 修正NG（オーナー判断）
- アーキテクチャ変更・新機能追加 → 修正NG

## 既知の継続問題
- rs50wNULL問題: 【2026-04-13修正済み】_calc_rs()にrs50w追加・3か所の結果dictにも追加。次回bulk-update実行から反映予定。

## 2026-04-13（AM: rs50w追加）
- **修正**: run_screen_full.py の `_calc_rs()` に rs50w を追加
  - 原因: `_calc_rs()` は rs6w/rs13w/rs26w のみ計算しており rs50w フィールドが存在しなかった
  - 修正: `"rs50w": safe_div(_pct(stock_closes, 50), _pct(bench_closes, 50))` を追加
  - 影響箇所: per-stock更新・update・bulk用 `_build_result_from_df()` の計3か所の結果dictにも `"rs50w": rs.get("rs50w")` を追加
  - パターン: 新フィールドを追加する際は _calc_rs() と全3か所の出力dictを同時に更新すること
  - 注意: run_screen_full.py の rs50w=n=50 は「50取引日」定義（stock_mcp_server.py の「50週×5日=250日」とは異なる）

## 2026-04-13（PM: simulation_log.json 価格・仮説更新）
- **修正**: simulation_log.json のフジクラ（5803）current_price 不一致解消
  - 原因: last_updated="2026-04-11" のまま4/13終値が反映されていなかった
  - 修正内容: current_price 5,028 → 5,698 / current_pct 4.75 → 18.71% / last_updated → "2026-04-13"
  - 確認方法: verification.md・internal_audit.md・risk.md が全て 5,698 円を一致して記載
  - パターン: 複数チームが同一価格を記載している場合はその値を採用する（多数決原則）
- **修正**: 全5銘柄の daily_log に 4/13 エントリー追加（3076・3003 は daily_log が空だった）
  - パターン: start_date からの経過日数と daily_log 件数が一致しない場合は欠落エントリーを補完する
- **修正**: 全銘柄の current_hypothesis を 4/14 向け翌日仮説に更新
  - ヒューリック（3003）のみ leading_scenario を base → bear に変更（金利急騰リスク反映）
  - パターン: 当日レポートが「リスク最優先注意」を表明した銘柄は bear に切替えること
- **判断**: 価格自動更新問題はオーナー対応事項としてエスカレーション（run_teams.py 改修が必要）
