#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidatePattern('^[a-z][a-z0-9-]{1,30}$')][string]$VmName = 'ml-lab',
    [ValidateRange(2, 16)][int]$Cpus = 2,
    [ValidatePattern('^[1-9][0-9]*G$')][string]$Memory = '4G',
    [ValidatePattern('^[2-9][0-9]G$')][string]$Disk = '30G',
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$WindowsEvidence = Join-Path $ProjectPath 'evidence/windows'
New-Item -ItemType Directory -Force $WindowsEvidence | Out-Null
$Utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-Utf8([string]$Path, [string]$Content) { [IO.File]::WriteAllText($Path, $Content, $Utf8) }
function Check-Native([string]$Operation) {
    if ($LASTEXITCODE -ne 0) { throw ($Operation + ' failed with exit code ' + $LASTEXITCODE) }
}
foreach ($tool in @('multipass', 'ssh', 'ssh-keygen', 'ssh-add', 'scp', 'tar')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw ('Missing ' + $tool + '. Run prepare-windows.ps1 first, then open a new PowerShell window.')
    }
}
$KeyPath = Join-Path $env:USERPROFILE ('.ssh/id_ed25519_' + $VmName)
$KnownHosts = Join-Path $env:USERPROFILE ('.ssh/known_hosts_' + $VmName)
$ConfigPath = Join-Path $env:USERPROFILE ('.ssh/config_' + $VmName)
New-Item -ItemType Directory -Force (Split-Path $KeyPath) | Out-Null
if (-not (Test-Path -LiteralPath $KeyPath)) {
    Write-Host 'Create the SSH key on this Windows client. Use a passphrase; ssh-agent will cache it.'
    & ssh-keygen -t ed25519 -a 64 -f $KeyPath -C ('lab1-' + $VmName)
    Check-Native 'ssh-keygen'
}
if (-not (Test-Path -LiteralPath ($KeyPath + '.pub'))) { throw 'The public key file is missing.' }
# A passphrase is entered interactively and is never stored in the project.
& ssh-add $KeyPath
Check-Native 'ssh-add (start the Windows ssh-agent service if it is stopped)'
$PublicKey = [IO.File]::ReadAllText($KeyPath + '.pub').Trim()
if ($PublicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+(?: .*)?$') { throw 'Expected an Ed25519 public key.' }

Start-Transcript -Path (Join-Path $WindowsEvidence 'setup-transcript.txt') -Force | Out-Null
$HoldSession = $null
$CloudInitPath = $null
$SourceArchive = $null
$ResultsArchive = $null
try {
    & multipass version
    Check-Native 'multipass version'
    $list = (& multipass list --format json | Out-String | ConvertFrom-Json)
    Check-Native 'multipass list'
    $existing = @($list.list | Where-Object { $_.name -eq $VmName })
    if ($existing.Count -eq 0) {
        $CloudInitPath = Join-Path ([IO.Path]::GetTempPath()) ('ml-lab-cloud-init-' + [guid]::NewGuid().ToString() + '.yaml')
        $cloudInit = @"
#cloud-config
users:
  - default
  - name: mluser
    gecos: ML development user
    shell: /bin/bash
    lock_passwd: true
    groups: []
    sudo: []
    ssh_authorized_keys:
      - $PublicKey
write_files:
  - path: /var/lib/ml-lab/managed-by-lab1
    owner: root:root
    permissions: '0444'
    content: nlp-lab1-2026
"@
        Write-Utf8 $CloudInitPath ($cloudInit -replace "`r`n", "`n")
        & multipass launch 24.04 --name $VmName --cpus $Cpus --memory $Memory --disk $Disk --timeout 1800 --cloud-init $CloudInitPath
        Check-Native 'multipass launch'
    } else {
        & multipass start $VmName
        Check-Native 'multipass start'
    }
    & multipass exec $VmName -- sudo cloud-init status --wait
    Check-Native 'cloud-init'
    $marker = (& multipass exec $VmName -- sudo cat /var/lib/ml-lab/managed-by-lab1 | Out-String).Trim()
    Check-Native 'VM ownership marker'
    if ($marker -ne 'nlp-lab1-2026') { throw 'Refusing to modify a VM not created for this lab.' }

    function Update-Connection {
        $info = (& multipass info $VmName --format json | Out-String | ConvertFrom-Json)
        Check-Native 'multipass info'
        $addresses = @($info.info.$VmName.ipv4)
        if ($addresses.Count -eq 0) { throw 'The VM has no IPv4 address.' }
        $script:ServerAddress = $addresses[0]
        if ($script:ServerAddress -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw 'Unexpected VM address.' }
        # Trust the host key obtained through the local authenticated Multipass management channel.
        $hostKey = (& multipass exec $VmName -- sudo cat /etc/ssh/ssh_host_ed25519_key.pub | Out-String).Trim()
        Check-Native 'guest host public key'
        if ($hostKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+(?: .*)?$') { throw 'Invalid host public key.' }
        if (Test-Path -LiteralPath $KnownHosts) {
            $oldKey = [IO.File]::ReadAllText($KnownHosts).Trim() -replace '^\S+ ', ''
            if ($oldKey -ne $hostKey) { throw 'VM host key changed. Verify a rebuilt VM before replacing known_hosts.' }
        }
        Write-Utf8 $KnownHosts ($script:ServerAddress + ' ' + $hostKey + "`n")
        $config = @"
Host ml-lab
    HostName $script:ServerAddress
    User mluser
    Port 22
    IdentityFile "$($KeyPath.Replace('\','/'))"
    UserKnownHostsFile "$($KnownHosts.Replace('\','/'))"
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 30
"@
        Write-Utf8 $ConfigPath ($config + "`n")
    }
    Update-Connection
    & ssh -F $ConfigPath -o BatchMode=yes ml-lab 'set -e; id; groups; test "$(id -un)" = mluser; touch /home/mluser/.lab1-key-verified'
    Check-Native 'initial SSH public-key login'

    & multipass exec $VmName -- test -d /home/mluser/ml-project
    $projectExists = ($LASTEXITCODE -eq 0)
    if ($projectExists -and -not $Resume) {
        throw 'The lab project already exists. Use -Resume to reuse it without overwriting, or a new -VmName.'
    }
    if (-not $projectExists) {
        # Archive excludes local virtual environments and previous VM evidence.
        $SourceArchive = Join-Path ([IO.Path]::GetTempPath()) ('ml-lab-source-' + [guid]::NewGuid().ToString() + '.tar.gz')
        & tar -czf $SourceArchive --exclude=.venv --exclude=__pycache__ --exclude=.ipynb_checkpoints --exclude=evidence/vm --exclude=evidence/windows -C $ProjectPath .
        Check-Native 'source archive'
        & scp -F $ConfigPath $SourceArchive 'ml-lab:/home/mluser/lab1-source.tar.gz'
        Check-Native 'source transfer'
        & ssh -F $ConfigPath -o BatchMode=yes ml-lab 'set -e; mkdir -p /home/mluser/ml-project; tar -xzf /home/mluser/lab1-source.tar.gz -C /home/mluser/ml-project; rm /home/mluser/lab1-source.tar.gz'
        Check-Native 'source extraction'
    }
    & multipass exec $VmName -- sudo bash /home/mluser/ml-project/scripts/install_system.sh
    Check-Native 'system installation'
    & multipass exec $VmName -- test -f /var/run/reboot-required
    if ($LASTEXITCODE -eq 0) {
        & multipass restart $VmName
        Check-Native 'VM restart after updates'
        Update-Connection
        & ssh -F $ConfigPath -o BatchMode=yes ml-lab 'id; test "$(id -un)" = mluser'
        Check-Native 'SSH after VM restart'
    }
    & multipass exec $VmName -- sudo -H -u mluser python3 /home/mluser/ml-project/scripts/download_dataset.py
    Check-Native 'dataset download and pinned checksum verification'
    & multipass exec $VmName -- sudo bash /home/mluser/ml-project/scripts/protect_baseline.sh
    Check-Native 'protected integrity reference'

    # Keep an authenticated SSH session established throughout hardening.
    $HoldSession = Start-Job -ScriptBlock { param($cfg) & ssh -F $cfg -o BatchMode=yes -N ml-lab } -ArgumentList $ConfigPath
    Start-Sleep -Seconds 2
    if ($HoldSession.State -ne 'Running') { throw 'Could not keep the initial SSH session open.' }
    & multipass exec $VmName -- sudo bash /home/mluser/ml-project/scripts/harden_vm.sh --key-login-verified
    Check-Native 'SSH and UFW hardening'
    $keyProof = & ssh -F $ConfigPath -o BatchMode=yes -o PreferredAuthentications=publickey ml-lab 'id; groups; test "$(id -un)" = mluser'
    Check-Native 'NEW SSH key session after firewall activation'
    Write-Utf8 (Join-Path $WindowsEvidence 'ssh-login-after.txt') ($keyProof -join "`n")
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $rootProof = & ssh -F $ConfigPath -o BatchMode=yes -o PreferredAuthentications=publickey -l root ml-lab true 2>&1
    $rootCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    Write-Utf8 (Join-Path $WindowsEvidence 'root-login-denied.txt') ($rootProof -join "`n")
    Write-Utf8 (Join-Path $WindowsEvidence 'root-login.exitcode') ([string]$rootCode)
    if ($rootCode -ne 255 -or ($rootProof -join ' ') -notmatch 'Permission denied') {
        throw 'Root denial could not be established. Rollback remains scheduled; inspect connectivity.'
    }
    & multipass exec $VmName -- sudo bash /home/mluser/ml-project/scripts/confirm_hardening.sh
    Check-Native 'hardening confirmation'
    Stop-Job $HoldSession
    Remove-Job $HoldSession
    $HoldSession = $null

    & multipass exec $VmName -- sudo -H -u mluser bash /home/mluser/ml-project/scripts/setup_project.sh
    Check-Native 'Python, notebook, integrity and dependency checks'
    & multipass exec $VmName -- sudo bash /home/mluser/ml-project/scripts/collect_security.sh
    Check-Native 'VM evidence collection'

    if (Get-Command code -ErrorAction SilentlyContinue) {
        $codeVersion = & code --version
        Write-Utf8 (Join-Path $WindowsEvidence 'vscode-version.txt') ($codeVersion -join "`n")
        & code --install-extension ms-vscode-remote.remote-ssh
        Check-Native 'VS Code Remote SSH extension'
    } else {
        Write-Warning 'VS Code is not installed or not in PATH. The IDE requirement remains pending.'
    }
    $ClientFiles = @('ssh-login-after.txt', 'root-login-denied.txt', 'root-login.exitcode') | ForEach-Object { Join-Path $WindowsEvidence $_ }
    $CodeEvidence = Join-Path $WindowsEvidence 'vscode-version.txt'
    if (Test-Path -LiteralPath $CodeEvidence) { $ClientFiles += $CodeEvidence }
    & scp -F $ConfigPath @ClientFiles 'ml-lab:/home/mluser/ml-project/evidence/windows/'
    Check-Native 'client evidence transfer'
    & multipass exec $VmName -- sudo -H -u mluser /home/mluser/ml-project/.venv/bin/python /home/mluser/ml-project/scripts/build_vm_report.py
    Check-Native 'VM report'
    $ResultsArchive = Join-Path ([IO.Path]::GetTempPath()) ('ml-lab-results-' + [guid]::NewGuid().ToString() + '.tar.gz')
    & scp -F $ConfigPath 'ml-lab:/home/mluser/ml-project/evidence/vm-results.tar.gz' $ResultsArchive
    Check-Native 'VM results download'
    & tar -xzf $ResultsArchive -C $ProjectPath
    Check-Native 'VM results extraction'
    Write-Host ('Completed. VM: ' + $VmName + '; SSH: ssh -F "' + $ConfigPath + '" ml-lab')
    Write-Host 'Review docs/VM_REPORT.md and the real listening ports before submitting.'
    Write-Host 'Jupyter tunnel: add -L 127.0.0.1:8888:127.0.0.1:8888 to the SSH command.'
} finally {
    if ($null -ne $HoldSession) { Stop-Job $HoldSession -ErrorAction SilentlyContinue; Remove-Job $HoldSession -Force -ErrorAction SilentlyContinue }
    if ($CloudInitPath) { Remove-Item -LiteralPath $CloudInitPath -ErrorAction SilentlyContinue }
    if ($SourceArchive) { Remove-Item -LiteralPath $SourceArchive -ErrorAction SilentlyContinue }
    if ($ResultsArchive) { Remove-Item -LiteralPath $ResultsArchive -ErrorAction SilentlyContinue }
    Stop-Transcript | Out-Null
}
