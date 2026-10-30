<#
.SYNOPSIS
    确保 Windows 构建机上有可用的 Inno Setup 6+ 编译器（ISCC.exe）。

.DESCRIPTION
    优先复用已安装的 Inno Setup；否则依次尝试：
      1. 从官方 GitHub Release 直接下载固定版本（默认 6.7.4）并静默安装；
      2. Chocolatey 安装固定版本/最新版；
      3. winget 安装 JRSoftware.InnoSetup；
    每次安装后重新探测 ISCC.exe。成功时输出其绝对路径并 exit 0。

    注意：本脚本只用于构建机，不随应用分发；安装包本身完全离线。

.EXAMPLE
    $iscc = & .\scripts\install_inno.ps1 -Version 6.5.4
#>
[CmdletBinding()]
param(
    [string]$Version = '6.7.4'
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$findScript = Join-Path $scriptDir 'find_iscc.ps1'

function Update-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Find-Iscc {
    $output = & $findScript 2>$null
    if ($LASTEXITCODE -eq 0 -and $output) {
        $path = ($output | Select-Object -Last 1)
        try {
            $major = [int]((Get-Item -LiteralPath $path).VersionInfo.FileMajorPart)
        }
        catch {
            $major = 0
        }
        if ($major -ge 6) {
            return $path
        }
        Write-Warning "忽略旧版本 Inno Setup（需要 6+）：$path"
    }
    return $null
}

$iscc = Find-Iscc
if ($iscc) {
    Write-Host "Inno Setup 已安装：$iscc"
    Write-Output $iscc
    exit 0
}

# 0) 官方 GitHub Release 直接下载安装（runner 镜像可能不再自带 choco/winget；
#    Inno Setup 从 2026-03 起将下载迁移到 GitHub Releases）。
$githubTag = 'is-' + ($Version -replace '\.', '_')
$downloadUrl = "https://github.com/jrsoftware/issrc/releases/download/$githubTag/innosetup-$Version.exe"
$downloadDir = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$setupPath = Join-Path $downloadDir "innosetup-$Version.exe"
$customInstallDir = Join-Path $downloadDir 'InnoSetup6'
function Write-Diag([string]$Message) {
    [Console]::Error.WriteLine("DIAG(install_inno): $Message")
}
try {
    Write-Host "尝试从官方 GitHub Release 下载 Inno Setup $Version ..."
    Write-Diag "url=$downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $setupPath -UseBasicParsing -TimeoutSec 180
    $size = if (Test-Path -LiteralPath $setupPath) { (Get-Item -LiteralPath $setupPath).Length } else { 0 }
    Write-Diag "downloaded=$setupPath size=$size"
    if ($size -gt 5000000) {
        # 显式指定临时目录，避免安装到 Program Files 或用户目录后 find 脚本未覆盖。
        Write-Diag "installing to $customInstallDir (ALLUSERS)"
        $proc = Start-Process -FilePath $setupPath -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
            '/ALLUSERS', "/DIR=`"$customInstallDir`""
        ) -Wait -PassThru
        Write-Diag "installer exit=$($proc.ExitCode)"
        $directIscc = Join-Path $customInstallDir 'ISCC.exe'
        if (Test-Path -LiteralPath $directIscc) {
            Write-Host "Inno Setup 安装成功（GitHub Release）：$directIscc"
            Write-Output $directIscc
            exit 0
        }
        # 有些 Inno 版本忽略 /DIR，改为当前用户安装后继续探测。
        Write-Diag "ISCC not found at custom dir; try CURRENTUSER default install"
        $proc = Start-Process -FilePath $setupPath -ArgumentList @(
            '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/CURRENTUSER'
        ) -Wait -PassThru
        Write-Diag "currentuser installer exit=$($proc.ExitCode)"
        Update-ProcessPath
        $iscc = Find-Iscc
        if ($iscc) {
            Write-Host "Inno Setup 安装成功（GitHub Release）：$iscc"
            Write-Output $iscc
            exit 0
        }
        Write-Diag 'official installer finished but ISCC.exe still not found'
    }
}
catch {
    Write-Diag "GitHub Release download/install failed: $($_.Exception.Message)"
}

$choco = Get-Command choco.exe -ErrorAction SilentlyContinue
if ($choco) {
    Write-Host "未找到 Inno Setup，尝试 Chocolatey 安装固定版本 $Version ..."
    & choco install innosetup --version=$Version -y --no-progress --limit-output
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "固定版本 $Version 安装失败（exit $LASTEXITCODE），尝试 Chocolatey 最新版 ..."
        & choco install innosetup -y --no-progress --limit-output
    }
    Update-ProcessPath
    $iscc = Find-Iscc
    if ($iscc) {
        Write-Host "Inno Setup 安装成功：$iscc"
        Write-Output $iscc
        exit 0
    }
}

$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host '尝试通过 winget 安装 JRSoftware.InnoSetup ...'
    & winget install --id JRSoftware.InnoSetup -e --silent --accept-source-agreements --accept-package-agreements --disable-interactivity
    Update-ProcessPath
    $iscc = Find-Iscc
    if ($iscc) {
        Write-Host "Inno Setup 安装成功：$iscc"
        Write-Output $iscc
        exit 0
    }
}

Write-Error ("无法自动安装 Inno Setup。请手动安装 Inno Setup 6.5+（https://jrsoftware.org/isdl.php），" +
    "确保存在 C:\Program Files (x86)\Inno Setup 6\ISCC.exe，或用 -IsccPath / 环境变量 ISCC_PATH 指定。")
exit 1
