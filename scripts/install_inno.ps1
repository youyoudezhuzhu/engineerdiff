<#
.SYNOPSIS
    确保 Windows 构建机上有可用的 Inno Setup 6+ 编译器（ISCC.exe）。

.DESCRIPTION
    优先复用已安装的 Inno Setup；否则依次尝试：
      1. Chocolatey 安装固定版本（默认 6.5.4，与仓库内简体中文语言文件匹配）；
      2. Chocolatey 安装最新版；
      3. winget 安装 JRSoftware.InnoSetup；
    每次安装后重新探测 ISCC.exe。成功时输出其绝对路径并 exit 0。

    注意：本脚本只用于构建机，不随应用分发；安装包本身完全离线。

.EXAMPLE
    $iscc = & .\scripts\install_inno.ps1 -Version 6.5.4
#>
[CmdletBinding()]
param(
    [string]$Version = '6.5.4'
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
