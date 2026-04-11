# run_daily_screening.ps1
# 毎日 15:00 JST に自動実行 — スクリーニング + invest-data に push
# タスクスケジューラから呼び出す
#
# 変更履歴:
#   2026-04-08: --fresh → --bulk-update に変更（数分で完了するように最適化）
#   2026-04-11: エントリーフィルタースクリーニング（entry_screen_v3.py）を追加

$ErrorActionPreference = "Stop"
$BASE   = "C:\Users\yohei\Documents\invest-system-github"
$DATA   = "C:\Users\yohei\Documents\invest-data"
$PYTHON = "C:\Users\yohei\AppData\Local\Python\bin\python.exe"
$LOG    = "$BASE\logs\screening_$(Get-Date -Format 'yyyyMMdd_HHmm').log"

New-Item -ItemType Directory -Force -Path "$BASE\logs" | Out-Null

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LOG -Append
}

Log "=== 日次スクリーニング開始 ==="

# 1. スクリーニング実行（bulk-update: 差分更新、APIコール約20回、数分で完了）
Log "screen_full (bulk-update) 開始..."
Set-Location $BASE
& $PYTHON run_screen_full.py --bulk-update 2>&1 | Tee-Object -FilePath $LOG -Append
if ($LASTEXITCODE -ne 0) { Log "WARNING: screen_full.py エラー (続行)" }

# 2. エントリーフィルタースクリーニング（SQLiteのみ・約1秒）
Log "エントリーフィルタースクリーニング開始..."
$env:INVEST_BASE_DIR   = "C:\Users\yohei\Documents\invest-system"
$env:INVEST_GITHUB_DIR = $BASE
Set-Location $BASE
& $PYTHON reports\entry_screen_v3.py 2>&1 | Tee-Object -FilePath $LOG -Append
if ($LASTEXITCODE -ne 0) { Log "WARNING: entry_screen_v3.py エラー (続行)" }

# 3. screen_full_results.json + エントリー結果 を invest-data に同期
$src = "$BASE\data\screen_full_results.json"
$dst = "$DATA\screen_full_results.json"
if (Test-Path $src) {
    Copy-Item $src $dst -Force
    Log "screen_full_results.json を invest-data にコピー"
} else {
    Log "WARNING: screen_full_results.json が見つかりません"
}
$entrySrc = "$BASE\reports\entry_screen_result.json"
if (Test-Path $entrySrc) {
    Copy-Item $entrySrc "$DATA\entry_screen_result.json" -Force
    Log "entry_screen_result.json を invest-data にコピー"
}

# 4. invest-data を git push
Log "invest-data を GitHub に push..."
Set-Location $DATA
git add screen_full_results.json entry_screen_result.json
$today = Get-Date -Format "yyyy-MM-dd"
git commit -m "screening $today (local)" --allow-empty
git push origin main 2>&1 | Tee-Object -FilePath $LOG -Append
if ($LASTEXITCODE -ne 0) { Log "WARNING: git push エラー" }

Log "=== スクリーニング完了 ==="
