# tests/ — スモークテスト

リファクタで機能が壊れていないかを素早く検証する最小限のテスト。

## 実行方法

```bash
python tests/smoke_test.py
```

全合格なら exit code 0、1 件でも失敗なら 1。

## 何をテストしているか

| テスト | 内容 |
|---|---|
| モジュールインポート | `run_teams` と `stock_mcp_server` が読み込めるか |
| `_score_num` | "5/7" → 5 などの変換 |
| `_rs26w` | rs50w/rs26w フォールバック |
| `screen_to_list` | dict ↔ list 変換・エラー除外 |
| `detect_phase` | 空データ → Defend、Attack 相場判定 |
| 実データ整合性 | `data/screen_full_results.json` が dict 形式・1000+ 銘柄 |
| `_minervini` | 7 条件スコア計算（ダミー 60 日データ） |

## 使い方（リファクタ時）

1. **Phase A/B/C の前に実行** → 基準状態を確認（全合格を確認）
2. ファイル分割後に再実行 → **同じ結果が出るか**確認
3. 失敗したら `git tag refactor-backup-20260418` に戻す

## 原則

- API 課金しない（Claude / Gemini / J-Quants を呼ばない）
- 実行時間は 10 秒以内
- プログラミング未経験でも、✅/❌ で判断できる
