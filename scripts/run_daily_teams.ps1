# run_daily_teams.ps1
# 毎日 16:35 JST に自動実行 — 8チームレポート生成 + invest-data に push
# タスクスケジューラから呼び出す

$ErrorActionPreference = "Stop"
$BASE   = "C:\Users\yohei\Documents\invest-system-github"
$DATA   = "C:\Users\yohei\Documents\invest-data"
$PYTHON = "C:\Users\yohei\AppData\Local\Python\bin\python.exe"
$LOG    = "$BASE\logs\teams_$(Get-Date -Format 'yyyyMMdd_HHmm').log"

New-Item -ItemType Directory -Force -Path "$BASE\logs" | Out-Null

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LOG -Append
}

Log "=== 8チームレポート生成開始 ==="

# 環境変数読み込み（.env ファイルから）
$envFile = "$BASE\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^([^#][^=]*)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
    Log ".env 読み込み完了"
} else {
    Log "WARNING: .env ファイルなし — 環境変数は既存のものを使用"
}

# 1. 8チームレポート実行
Log "run_teams.py 開始..."
Set-Location $BASE
& $PYTHON run_teams.py 2>&1 | Tee-Object -FilePath $LOG -Append
if ($LASTEXITCODE -ne 0) { Log "WARNING: run_teams.py エラー (続行)" }

# 2. reports/ を invest-data に同期
$srcReports = "$BASE\reports\daily"
$dstReports = "$DATA\reports"
if (Test-Path $srcReports) {
    Copy-Item "$srcReports\*" $dstReports -Recurse -Force
    Log "reports/daily/* を invest-data/reports に同期"
}

# 3. invest-data を git push
Log "invest-data を GitHub に push..."
Set-Location $DATA
git add reports/
$today = Get-Date -Format "yyyy-MM-dd"
git commit -m "daily report $today (local)" --allow-empty
git push origin main 2>&1 | Tee-Object -FilePath $LOG -Append
if ($LASTEXITCODE -ne 0) { Log "WARNING: git push エラー" }

Log "=== 8チームレポート完了 ==="
