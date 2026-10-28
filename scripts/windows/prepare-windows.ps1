#Requires -Version 5.1
#Requires -RunAsAdministrator
# Installs prerequisites only. It never reboots Windows automatically.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
$feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
$needsRestart = $false
if ($feature.State -ne 'Enabled') {
    $enabled = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
    $needsRestart = $enabled.RestartNeeded
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    $capability = Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
    if ($capability.RestartNeeded) { $needsRestart = $true }
}
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service -Name ssh-agent

if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
    $release = Invoke-RestMethod 'https://api.github.com/repos/canonical/multipass/releases/latest'
    if ([version]($release.tag_name -replace '^v', '') -lt [version]'1.17.0') {
        throw 'Multipass 1.17 or newer is required for the current Windows Home-compatible HCS path.'
    }
    $asset = @($release.assets | Where-Object { $_.name -match 'win64\.msi$' })
    if ($asset.Count -ne 1) { throw 'Could not identify the official Windows installer.' }
    $installer = Join-Path ([IO.Path]::GetTempPath()) ('ml-lab-' + [guid]::NewGuid().ToString() + '.msi')
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $asset[0].browser_download_url -OutFile $installer
        $signature = Get-AuthenticodeSignature $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Canonical') {
            throw 'The installer does not have a valid Canonical signature.'
        }
        Write-Host ('Installer publisher: ' + $signature.SignerCertificate.Subject)
        Get-FileHash $installer -Algorithm SHA256 | Format-List
        # Show the signed installer UI; do not hide installation failures.
        $process = Start-Process msiexec.exe -ArgumentList @('/i', ('"' + $installer + '"'), '/norestart') -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010)) { throw ('Installer exit code: ' + $process.ExitCode) }
        if ($process.ExitCode -eq 3010) { $needsRestart = $true }
    } finally {
        Remove-Item -LiteralPath $installer -ErrorAction SilentlyContinue
    }
}
if ($needsRestart) {
    Write-Host 'Restart Windows, then open a NEW regular PowerShell window and run start-lab.ps1.'
} else {
    Write-Host 'Open a NEW regular PowerShell window and run start-lab.ps1.'
}
Write-Host 'VS Code can be installed as your regular user from https://code.visualstudio.com/download .'
Write-Host 'Hardware virtualization (Intel VT-x / AMD-V) must be enabled in UEFI.'

