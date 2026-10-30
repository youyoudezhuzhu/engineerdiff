<#
.SYNOPSIS
    查找 Windows 上的 Inno Setup 编译器 ISCC.exe。

.DESCRIPTION
    依次探测：
      1. 环境变量 ISCC_PATH（显式覆盖，优先级最高）；
      2. PATH 中的 ISCC.exe（Chocolatey shim / 手动加入 PATH）；
      3. 常见安装目录：{Program Files (x86)|Program Files}\Inno Setup {6|7}\ISCC.exe
         （GitHub Actions 任务约定路径 C:\Program Files (x86)\Inno Setup 6\ISCC.exe 在此命中）；
      4. 注册表卸载项（InstallLocation / UninstallString 推导），覆盖自定义安装目录。

    找到时向标准输出写一行绝对路径并 exit 0；找不到时 exit 1（便于调用方判断）。

.EXAMPLE
    $iscc = & .\scripts\find_iscc.ps1
#>
[CmdletBinding()]
param(
    [switch]$VerboseOutput
)

$ErrorActionPreference = 'Stop'

$candidates = [System.Collections.Generic.List[string]]::new()

function Add-Candidate {
    param([string]$Path)
    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        $candidates.Add($Path) | Out-Null
    }
}

# 1) 显式覆盖
if ($env:ISCC_PATH) {
    Add-Candidate $env:ISCC_PATH
}

# 2) PATH
$cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($cmd -and $cmd.Source) {
    Add-Candidate $cmd.Source
}

# 3) 常见安装目录（含任务约定的 Program Files (x86)\Inno Setup 6）
$bases = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:ProgramW6432) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
foreach ($base in $bases) {
    foreach ($major in @('6', '7')) {
        Add-Candidate (Join-Path $base "Inno Setup $major\ISCC.exe")
    }
}

# 4) 注册表卸载项
$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($uninstallRoot in $uninstallRoots) {
    $items = Get-ItemProperty -Path $uninstallRoot -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        if (-not $item.DisplayName -or $item.DisplayName -notmatch '^Inno Setup') { continue }
        if ($item.InstallLocation) {
            Add-Candidate (Join-Path $item.InstallLocation 'ISCC.exe')
        }
        if ($item.UninstallString) {
            $match = [regex]::Match([string]$item.UninstallString, '"([^"]+)"')
            if ($match.Success) {
                $dir = Split-Path -Parent $match.Groups[1].Value
                Add-Candidate (Join-Path $dir 'ISCC.exe')
            }
        }
    }
}

foreach ($candidate in $candidates) {
    $resolved = $null
    try {
        $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    }
    catch {
        continue
    }
    if ($resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        if ($VerboseOutput) {
            Write-Host "找到 Inno Setup 编译器：$resolved"
        }
        Write-Output $resolved
        exit 0
    }
}

if ($VerboseOutput) {
    Write-Warning '未找到 Inno Setup（ISCC.exe）。可执行 scripts/install_inno.ps1，或用 -IsccPath 指定。'
}
exit 1
