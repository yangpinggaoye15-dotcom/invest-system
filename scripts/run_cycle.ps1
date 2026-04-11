# run_cycle.ps1
# PDCAサイクル実行スクリプト
#
# 時刻ベース分岐:
#   09:00 / 12:00 / 15:00  →  スクリーニングのみ
#                              （J-Quantsは15:30引け後に更新されるため、teamsはまだ動かさない）
#   18:00                  →  チームレポートのみ
#                              （J-Quants終値確定後。_fetch_fresh_price()で最新値を取得）
#
# タスクスケジューラから呼び出す
# 変更履歴:
#   2026-04-07: 9/12/15サイクル作成
#   2026-04-09: 時刻ベース分岐追加（仮説ギャップ修正）

$ErrorActionPreference = "Continue"
$BASE   = "C:\Users\yohei\Documents\invest-system-github"
$SLOT   = [int](Get-Date -Format "HHmm")   # 例: 900, 1200, 1500, 1800
$LOG    = "$BASE\logs\cycle_$(Get-Date -Format 'yyyyMMdd_HHmm').log"

New-Item -ItemType Directory -Force -Path "$BASE\logs" | Out-Null

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LOG -Append
}

Log "=========================================="
Log "=== PDCAサイクル開始 (slot=$SLOT) ==="
Log "=========================================="

$dow = (Get-Date).DayOfWeek
$isWeekday = ($dow -ne "Saturday" -and $dow -ne "Sunday")

# ── STEP 1: スクリーニング（17:00前・平日のみ）────────────────────────────
if ($SLOT -lt 1700) {
    if ($isWeekday) {
        Log "--- [スクリーニングモード] J-Quants未確定のためteamsはスキップ ---"
        Log "--- [1/1] スクリーニング開始 ---"
        & powershell.exe -NonInteractive -ExecutionPolicy Bypass `
            -File "$BASE\scripts\run_daily_screening.ps1" 2>&1 | Tee-Object -FilePath $LOG -Append
        Log "--- [1/1] スクリーニング完了 ---"
    } else {
        Log "--- スクリーニングスキップ (週末) ---"
    }
    Log "=== PDCAサイクル終了 (slot=$SLOT) ==="
    exit 0
}

# ── STEP 2: チームレポート（17:00以降・毎日）─────────────────────────────
# この時刻帯はJ-Quants終値確定済み (_fetch_fresh_price が最新値を取得)
Log "--- [チームレポートモード] J-Quants終値確定後 ---"

# 平日なら念のためスクリーニングを先行（差分更新のみ・高速）
if ($isWeekday) {
    Log "--- [1/2] スクリーニング（最終確認・差分更新）---"
    & powershell.exe -NonInteractive -ExecutionPolicy Bypass `
        -File "$BASE\scripts\run_daily_screening.ps1" 2>&1 | Tee-Object -FilePath $LOG -Append
    Log "--- [1/2] スクリーニング完了 ---"
} else {
    Log "--- スクリーニングスキップ (週末) ---"
}

Log "--- [2/2] 8チームレポート ---"
& powershell.exe -NonInteractive -ExecutionPolicy Bypass `
    -File "$BASE\scripts\run_daily_teams.ps1" 2>&1 | Tee-Object -FilePath $LOG -Append
Log "--- [2/2] レポート完了 ---"

Log "=== PDCAサイクル終了 (slot=$SLOT) ==="
