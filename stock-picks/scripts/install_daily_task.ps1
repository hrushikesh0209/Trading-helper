# Registers a Windows scheduled task that updates the Nifty 500 price store
# every weekday at 4:30 pm IST. It runs only Python (no Claude, no tokens).
# If the laptop is off at 4:30 pm, it runs as soon as the laptop is back on.
# After the prices it runs the screener, so the day's lists are ready for /stock-picks.
#
# Install:  powershell -ExecutionPolicy Bypass -File install_daily_task.ps1
# Remove:   Unregister-ScheduledTask -TaskName "TradingAgents Daily Market Data" -Confirm:$false

$name = "TradingAgents Daily Market Data"
$exe = "C:\Users\Dell\TradingAgents\.venv\Scripts\pythonw.exe"
$script = "C:\Users\Dell\.claude\skills\stock-picks\scripts\market_data.py"

$action = New-ScheduledTaskAction -Execute $exe -Argument "`"$script`" daily" -WorkingDirectory "C:\Users\Dell\TradingAgents"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 16:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "Updates D:\TradingAgentsData\market\market.db with the day's Nifty 500 prices (no Claude tokens)." | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $name
Write-Host "Installed '$name'. Next run: $($info.NextRunTime)"
Write-Host "Logs: D:\TradingAgentsData\market\logs\"
