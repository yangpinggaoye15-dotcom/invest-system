# Lessons Learned - エラーと学習事項

## 1. JSON NaN問題 (2026-03-26)
**症状**: サイトで「読み込み失敗」エラー
**原因**: screen_full_results.json に Python の float NaN が1810件混入。ブラウザの JSON.parse() は NaN を受け付けない。
**対策**: `_sanitize_nans()` が `_save_results()` 内で呼ばれているが、手動でJSONを更新した際にバイパスされた。
**再発防止**: JSON書き出し時は必ず `_sanitize_nans()` を通す。手動スクリプトでも同様。

## 2. データ二重更新 (2026-03-26)
**症状**: 15時に古いデータ、21時に最新データが表示
**原因**: Windows タスクスケジューラ（15:00, resume mode, ローカルのみ）と GitHub Actions（15:05, --fresh, invest-data push）が並行動作。GAの--freshは全銘柄スキャンで数時間かかる。
**対策**: GAに export_chart_data / export_fins_data を追加。Windows TSは廃止推奨。

## 3. export ファイルの sync 漏れ (2026-03-26)
**症状**: チャートと業績がサイトで表示されない
**原因**: daily_screening.yml の sync リストに fins_data.json が含まれていなかった。また export_chart_data / export_fins_data がワークフロー内で呼ばれていなかった。
**対策**: yml に fins_data.json 追加。screening 後に export を自動実行するステップ追加。

## 4. run_screen_full.py の _lookup バグ
**症状**: update() 関数で NameError
**原因**: `_lookup(code_4)` と呼んでいるが、正しい関数名は `_lookup_name(code_4)`
**対策**: update() 内の呼び出しを修正

## 5. plotly 依存の問題
**注意**: GitHub Actions で export_chart_data を実行するには plotly のインストールが必要。requirements.txt に plotly が含まれているが、pip install で明示的にインストールが必要。
