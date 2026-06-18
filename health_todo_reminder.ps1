$note = 'G:\ClaudeCode应用\60-产品需求\健康数字孪生系统-待办-2026-06-18.md'
try { Start-Process $note } catch {}
Add-Type -AssemblyName System.Windows.Forms
$msg = "健康数字孪生 · 待办提醒`n`n进行中：戴表同步后接通佳明真数据（登录选 N，避开 429）`n`n下一步三选一：`n  (a) 元气值加成 - 运动把元气加回去`n  (b) 华米 A2011 - huami-token 接通`n  (c) Switch 手柄真机联调`n`n详见已打开的待办笔记。"
[System.Windows.Forms.MessageBox]::Show($msg, '健康项目 · 待办提醒', 'OK', 'Information') | Out-Null