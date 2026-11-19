# 抓取失败弹窗（置顶显示在用户桌面上）
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32Msg {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);
}
"@

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log = Join-Path $root 'data\logs\scrape.log'
$tail = ''
try {
    if (Test-Path $log) {
        $tail = (Get-Content $log -Tail 6 -Encoding UTF8) -join "`n"
        if ($tail.Length -gt 600) { $tail = $tail.Substring($tail.Length - 600) }
    }
} catch { $tail = '（日志读取失败）' }

$msg = "Pjsk 卡牌雷达：本次自动抓取未成功！`r`n`r`n" +
       "请检查网络连接后，可手动运行 scripts\run_scrape.cmd 重试。`r`n" +
       "已有卡面不会被重复下载，重启抓取只补缺失部分。`r`n`r`n" +
       "--- 最近日志 ---`r`n$tail"

# 0x40000 TOPMOST | 0x10000 SETFOREGROUND | 0x30 ICONWARNING
[Win32Msg]::MessageBoxW([IntPtr]::Zero, $msg, 'Pjsk 卡牌雷达 · 抓取失败', 0x50030) | Out-Null
