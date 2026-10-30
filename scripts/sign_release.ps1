<#
.SYNOPSIS
    为 EngineerDiff 发布产物做 Authenticode 签名（需要代码签名证书）。
.DESCRIPTION
    可选脚本，不参与 CI。需要 Windows SDK 的 signtool.exe 与 .pfx 证书。
    推荐通过环境变量传入密码，避免进入 PowerShell 命令历史：
        $env:ENGINEERDIFF_SIGN_PFX = "C:\path\codesign.pfx"
        $env:ENGINEERDIFF_SIGN_PASSWORD = "***"
        powershell -ExecutionPolicy Bypass -File scripts\sign_release.ps1
    签名后请重新生成 sha256sums.txt。
#>
[CmdletBinding()]
param(
    [string]$PfxPath = $env:ENGINEERDIFF_SIGN_PFX,
    [string]$PfxPassword = $env:ENGINEERDIFF_SIGN_PASSWORD,
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [string]$Description = 'EngineerDiff'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($PfxPath) -or -not (Test-Path -LiteralPath $PfxPath)) {
    throw '请通过 -PfxPath 或 ENGINEERDIFF_SIGN_PFX 指定有效的 .pfx 证书。'
}

$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $signtool = Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $signtool -or -not (Test-Path -LiteralPath $signtool)) {
    throw '未找到 signtool.exe，请安装 Windows SDK。'
}

$files = @(
    (Join-Path $root 'dist\EngineerDiff\EngineerDiff.exe'),
    (Get-ChildItem -Path (Join-Path $root 'release') -Filter 'EngineerDiff-*-Setup-x64.exe' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if ($files.Count -eq 0) {
    throw '未找到可签名的 exe/安装包，请先运行 scripts\build_windows.ps1。'
}

foreach ($file in $files) {
    Write-Host "签名：$file"
    & $signtool sign /fd SHA256 /f $PfxPath /p $PfxPassword /tr $TimestampUrl /td SHA256 /d $Description $file
    if ($LASTEXITCODE -ne 0) { throw "签名失败：$file" }
    & $signtool verify /pa /v $file
    if ($LASTEXITCODE -ne 0) { throw "签名验证失败：$file" }
}
Write-Host '签名完成。请重新生成 release\sha256sums.txt 并上传新资产。' -ForegroundColor Green
