# CHANGELOG - invest-system 作業履歴

## 2026-03-26 v3 - サイト大幅拡張

### 追加機能
- 業績ページ: 過去5年FY + 四半期 + 予想 + 成長性サマリー
- 業績シミュレーション・株価シミュレーション
- 監視銘柄/ポートフォリオのサイト上での登録UI
- 日足/週足/月足の切り替え
- パターン判定理由の表示
- メモ機能（localStorage）
- 日足データのSQLite蓄積（daily_pricesテーブル）
- GitHub Actions自動パイプライン修正

### バグ修正
- screen_full_results.json に NaN値が1810件混入 → ブラウザで読み込み失敗
- ytd_high/vol_ratio/change_pct がresultsに未保存 → 年初来高値フィルタ動作せず
- fins_data.json が invest-data sync リストに未登録
- GitHub Actions で export_chart_data/export_fins_data が未実行

### 発見した問題
- Windows TS (15:00) と GitHub Actions (15:05) の二重実行
- run_screen_full.py update()内の _lookup() → _lookup_name() バグ

## 2026-03-25 v2 - ローソク足チャート + パターン判定

### 追加機能
- TradingView lightweight-charts によるローソク足チャート
- Cup with Handle / VCP / Flat Base パターン自動判定
- Plotly チャート生成 MCP ツール
- export_chart_data: サイト用データ生成
- パターンバッジ（CwH/VCP/Flat）をスクリーニングテーブルに追加

## 2026-03-25 v1 - 初期構築

### 機能
- Minervini 7条件スクリーニング
- RS (Relative Strength) vs 日経225
- ファンダメンタルデータ取得
- ポートフォリオ/監視銘柄管理（MCP）
- GitHub Pages ダッシュボード
- AI分析（Gemini/Claude連携）
