# setup_scheduler.ps1
# PDCA cycle スケジューラ設定
#
# タイムライン:
#   09:00  スクリーニングのみ（前日終値ベース・早期フィルタ）
#   12:00  スクリーニングのみ（日中更新確認）
#   15:00  スクリーニングのみ（引け直前・最終確認）
#   18:00  チームレポート（J-Quants終値確定後・_fetch_fresh_priceで最新値取得）
#
# 変更履歴:
#   2026-04-09: 18:00 teams専用スロット追加（仮説ギャップ修正対応）

$BASE = "C:\Users\yohei\Documents\invest-system-github"
$exe = "powershell.exe"
$cycleScript = "$BASE\scripts\run_cycle.ps1"
$arg = "-NonInteractive -ExecutionPolicy Bypass -File `"$cycleScript`""

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

# 旧タスクを全削除
foreach ($name in @("InvestSystem_DailyScreening","InvestSystem_DailyTeams",
                     "InvestSystem_Cycle_09","InvestSystem_Cycle_12",
                     "InvestSystem_Cycle_15","InvestSystem_Cycle_18")) {
    Unregister-ScheduledTask -TaskName $name -TaskPath "\InvestSystem\" `
        -Confirm:$false -ErrorAction SilentlyContinue
}

# 09:00 — スクリーニングのみ
$a09 = New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $BASE
$t09 = New-ScheduledTaskTrigger -Daily -At "09:00"
Register-ScheduledTask -TaskName "InvestSystem_Cycle_09" -TaskPath "\InvestSystem\" `
    -Action $a09 -Trigger $t09 -Settings $settings `
    -Description "PDCA 09:00 [スクリーニングのみ]" -Force | Out-Null
Write-Host "OK: Cycle_09 (09:00, スクリーニング) registered"

# 12:00 — スクリーニングのみ
$a12 = New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $BASE
$t12 = New-ScheduledTaskTrigger -Daily -At "12:00"
Register-ScheduledTask -TaskName "InvestSystem_Cycle_12" -TaskPath "\InvestSystem\" `
    -Action $a12 -Trigger $t12 -Settings $settings `
    -Description "PDCA 12:00 [スクリーニングのみ]" -Force | Out-Null
Write-Host "OK: Cycle_12 (12:00, スクリーニング) registered"

# 15:00 — スクリーニングのみ
$a15 = New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $BASE
$t15 = New-ScheduledTaskTrigger -Daily -At "15:00"
Register-ScheduledTask -TaskName "InvestSystem_Cycle_15" -TaskPath "\InvestSystem\" `
    -Action $a15 -Trigger $t15 -Settings $settings `
    -Description "PDCA 15:00 [スクリーニングのみ]" -Force | Out-Null
Write-Host "OK: Cycle_15 (15:00, スクリーニング) registered"

# 18:00 — チームレポート専用（J-Quants終値確定後）
$a18 = New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $BASE
$t18 = New-ScheduledTaskTrigger -Daily -At "18:00"
Register-ScheduledTask -TaskName "InvestSystem_Cycle_18" -TaskPath "\InvestSystem\" `
    -Action $a18 -Trigger $t18 -Settings $settings `
    -Description "PDCA 18:00 teams-only after J-Quants close" -Force | Out-Null
Write-Host "OK: Cycle_18 (18:00, チームレポート) registered"

Write-Host ""
Write-Host "=== 登録済みタスク ==="
Get-ScheduledTask -TaskPath "\InvestSystem\" | Select-Object TaskName, State, Description
