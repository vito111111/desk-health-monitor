# -*- coding: utf-8 -*-
# 桌前健康关怀助手 - 控制中心（启动 / 停止 / 打开页面）
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$Dir    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PyW    = "C:\Users\megarobo-BJ\AppData\Local\Programs\Python\Python313\pythonw.exe"
$Port   = 5005
$Url    = "http://127.0.0.1:$Port"
$AppPy  = Join-Path $Dir "app.py"

function Get-AppPid {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.OwningProcess }
    return $null
}

function Test-Running { return (Get-AppPid) -ne $null }

function Start-App {
    if (Test-Running) { Write-Host "  已经在运行了。" -ForegroundColor Yellow; return }
    Write-Host "  正在启动（摄像头初始化约需几秒）..." -ForegroundColor Cyan
    Start-Process -FilePath $PyW -ArgumentList "`"$AppPy`"" -WorkingDirectory $Dir -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 600
        if (Test-Running) {
            Write-Host "  已启动 ✓  浏览器将自动打开：$Url" -ForegroundColor Green
            return
        }
    }
    Write-Host "  启动超时，请检查摄像头是否被占用。" -ForegroundColor Red
}

function Stop-App {
    $procPid = Get-AppPid
    if (-not $procPid) {
        Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -like '*app.py*' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Write-Host "  已停止（未发现监听进程）。" -ForegroundColor Yellow
        return
    }
    Stop-Process -Id $procPid -Force
    Start-Sleep -Milliseconds 400
    Write-Host "  已停止 ✓  摄像头已释放。" -ForegroundColor Green
}

while ($true) {
    Clear-Host
    $running = Test-Running
    $status  = if ($running) { "● 运行中" } else { "○ 已停止" }
    $color   = if ($running) { "Green" } else { "DarkGray" }
    Write-Host ""
    Write-Host "  ════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host "     桌前健康关怀助手 · 控制中心" -ForegroundColor White
    Write-Host "  ════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host "     状态： " -NoNewline; Write-Host $status -ForegroundColor $color
    if ($running) {
        Write-Host "     自用： $Url/" -ForegroundColor Gray
        Write-Host "     管理： $Url/manage" -ForegroundColor Gray
    }
    Write-Host "  ────────────────────────────────────────" -ForegroundColor DarkCyan
    Write-Host "     [1] 启动" -ForegroundColor Green
    Write-Host "     [2] 停止" -ForegroundColor Red
    Write-Host "     [3] 打开页面（浏览器）" -ForegroundColor Cyan
    Write-Host "     [0] 退出本窗口（不影响后台运行）" -ForegroundColor DarkGray
    Write-Host "  ════════════════════════════════════════" -ForegroundColor DarkCyan
    Write-Host ""
    $k = Read-Host "  请选择"
    switch ($k) {
        '1' { Start-App;  if (-not $running) { Start-Sleep -Milliseconds 1200; Start-Process $Url } ; Read-Host "  回车返回菜单" }
        '2' { Stop-App;   Read-Host "  回车返回菜单" }
        '3' { Start-Process $Url }
        '0' { break }
        default { }
    }
}
