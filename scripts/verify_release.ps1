<#
.SYNOPSIS
Runs VMA release verification with evidence outside the repository.
.DESCRIPTION
quick runs local regression checks. full evaluates every release gate and fails
closed when prerequisites are missing. resume reuses whole-gate PASS results
only when the source snapshot hash is unchanged, then reruns blocked gates.
Set VMA_INTEGRITY_TEST_ROOT or pass -IntegrityTestRoot to identify the existing
external integrity-test directory. There is intentionally no machine-specific
fallback; verification stops if this protected root is not configured/readable.
.EXAMPLE
pwsh -NoProfile -File scripts/verify_release.ps1 quick -IntegrityTestRoot $env:VMA_INTEGRITY_TEST_ROOT
.EXAMPLE
pwsh -NoProfile -File scripts/verify_release.ps1 full -IntegrityTestRoot $env:VMA_INTEGRITY_TEST_ROOT -AllowNetwork
.EXAMPLE
pwsh -NoProfile -File scripts/verify_release.ps1 resume -IntegrityTestRoot $env:VMA_INTEGRITY_TEST_ROOT -FfmpegPath C:\approved\ffmpeg.exe
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("quick", "full", "resume")]
    [string]$Mode = "quick",
    [string]$EvidenceRoot = (Join-Path $env:LOCALAPPDATA "VMA\release-verification"),
    [string]$IntegrityTestRoot = $env:VMA_INTEGRITY_TEST_ROOT,
    [string]$FfmpegPath = $env:VMA_REAL_CODEC_FFMPEG,
    [string]$Wheelhouse,
    [string]$LinuxEvidencePath,
    [string]$BrowserEvidencePath,
    [switch]$AllowNetwork
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Test-PathWithin([string]$Candidate, [string]$Parent) {
    $candidateFull = [IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return $candidateFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith($parentFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

$integrityRootConfigured = -not [string]::IsNullOrWhiteSpace($IntegrityTestRoot)
if (-not $integrityRootConfigured) {
    throw "IntegrityTestRoot is required; pass -IntegrityTestRoot or set VMA_INTEGRITY_TEST_ROOT. Refusing to omit the external protected directory."
}
$IntegrityTestRoot = [IO.Path]::GetFullPath($IntegrityTestRoot)
if (-not (Test-Path -LiteralPath $IntegrityTestRoot -PathType Container)) {
    throw "IntegrityTestRoot must identify an existing, accessible directory."
}
if ((Test-PathWithin $IntegrityTestRoot $RepoRoot) -or (Test-PathWithin $RepoRoot $IntegrityTestRoot)) {
    throw "IntegrityTestRoot must be disjoint from the repository."
}

$ProtectedRoots = @(
    (Join-Path $RepoRoot "tests\VMA_test_audio_pack"),
    $IntegrityTestRoot,
    (Join-Path $RepoRoot ".pytest_tmp"),
    (Join-Path $RepoRoot "tmp\pytest_precommit_validation")
)

$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
if (Test-PathWithin $EvidenceRoot $RepoRoot) { throw "EvidenceRoot must be outside the repository." }
foreach ($protected in $ProtectedRoots) {
    if (Test-PathWithin $EvidenceRoot $protected) { throw "EvidenceRoot must not be inside $protected" }
}

$RunId = (Get-Date -Format "yyyyMMddTHHmmss") + "-$Mode"
$RunDir = Join-Path $EvidenceRoot $RunId
$LogsDir = Join-Path $RunDir "logs"
$ReportsDir = Join-Path $RunDir "reports"
$ArtifactsDir = Join-Path $RunDir "artifacts"
$TempDir = Join-Path $RunDir "temp"
foreach ($path in @($EvidenceRoot,$RunDir,$LogsDir,$ReportsDir,$ArtifactsDir,$TempDir)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}

$StartedUtc=(Get-Date).ToUniversalTime()
$GateTitles=[ordered]@{
    A="Snapshot integrity"; B="Python and frontend tests"; C="Real codecs"
    D="Docker and production security"; E="Browser acceptance"
    F="Security scans and SBOM"; G="CI automation"
}
$Gates=[ordered]@{}
foreach ($id in $GateTitles.Keys) {
    $Gates[$id]=[ordered]@{
        Id=$id; Name=$GateTitles[$id]; Status="NOT_RUN"; Reason="Not evaluated"
        Checks=[Collections.Generic.List[object]]::new()
    }
}
$Quick=[ordered]@{Status="NOT_RUN";Reason="Not evaluated";Checks=[Collections.Generic.List[object]]::new()}
$Tools=[Collections.Generic.List[object]]::new()

function Get-ToolPath([string]$Name) {
    $tool=Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($tool) { return $tool.Source }
    return $null
}
function Get-SHA256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Get-TextSHA256([string]$Value) {
    $algorithm=[Security.Cryptography.SHA256]::Create()
    try {
        $bytes=[Text.Encoding]::UTF8.GetBytes($Value)
        return ([Convert]::ToHexString($algorithm.ComputeHash($bytes))).ToLowerInvariant()
    } finally {$algorithm.Dispose()}
}
function Invoke-Step {
    param([string]$Name,[string]$FilePath,[string[]]$Arguments=@(),
          [string]$WorkingDirectory=$RepoRoot,[hashtable]$Environment=@{})
    $logPath=Join-Path $LogsDir ((($Name -replace '[^A-Za-z0-9_.-]','_').Trim('_'))+".log")
    $watch=[Diagnostics.Stopwatch]::StartNew()
    $result=[ordered]@{Name=$Name;Command=((@($FilePath)+$Arguments)-join " ");ExitCode=$null;
        DurationSeconds=$null;LogPath=$logPath;Stdout="";Stderr="";Error=$null}
    try {
        $info=[Diagnostics.ProcessStartInfo]::new()
        $info.FileName=$FilePath;$info.WorkingDirectory=$WorkingDirectory
        $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true
        $info.RedirectStandardError=$true;$info.CreateNoWindow=$true
        foreach ($argument in $Arguments) {[void]$info.ArgumentList.Add($argument)}
        foreach ($entry in $Environment.GetEnumerator()) {$info.Environment[$entry.Key]=[string]$entry.Value}
        $process=[Diagnostics.Process]::new();$process.StartInfo=$info
        if (-not $process.Start()) {throw "Process did not start"}
        $outTask=$process.StandardOutput.ReadToEndAsync();$errTask=$process.StandardError.ReadToEndAsync()
        $process.WaitForExit();$result.ExitCode=$process.ExitCode
        $result.Stdout=$outTask.GetAwaiter().GetResult();$result.Stderr=$errTask.GetAwaiter().GetResult()
        @("COMMAND: $($result.Command)","EXIT_CODE: $($result.ExitCode)",
          "--- STDOUT ---",$result.Stdout,"--- STDERR ---",$result.Stderr) |
            Set-Content -LiteralPath $logPath -Encoding utf8
    } catch {
        $result.Error=$_.Exception.Message
        @("COMMAND: $($result.Command)","ERROR: $($result.Error)") |
            Set-Content -LiteralPath $logPath -Encoding utf8
    } finally {$watch.Stop();$result.DurationSeconds=[math]::Round($watch.Elapsed.TotalSeconds,3)}
    return [pscustomobject]$result
}
function Add-Check {
    param([Collections.Generic.List[object]]$Target,[string]$Name,[string]$Status,
          [string]$Reason,$Step=$null,[string]$EvidencePath=$null)
    $Target.Add([pscustomobject][ordered]@{Name=$Name;Status=$Status;Reason=$Reason;
        ExitCode=if($Step){$Step.ExitCode}else{$null};
        DurationSeconds=if($Step){$Step.DurationSeconds}else{$null};
        EvidencePath=if($Step){$Step.LogPath}else{$EvidencePath}})
}
function Set-Gate([string]$Id,[string]$Status,[string]$Reason) {
    $Gates[$Id].Status=$Status;$Gates[$Id].Reason=$Reason
}

function Get-ProtectedManifest {
    $roots=[Collections.Generic.List[object]]::new()
    foreach($root in $ProtectedRoots){
        $record=[ordered]@{Root=$root;Exists=$false;Files=@();Error=$null}
        try{
            if(-not(Test-Path -LiteralPath $root)){$roots.Add([pscustomobject]$record);continue}
            $record.Exists=$true;$rootItem=Get-Item -LiteralPath $root -ErrorAction Stop
            $sourceFiles=if($rootItem.PSIsContainer){
                @(Get-ChildItem -LiteralPath $root -File -Recurse -Force -ErrorAction Stop|Sort-Object FullName)
            }else{@($rootItem)}
            $record.Files=@(foreach($file in $sourceFiles){
                try{
                    $relative=if($rootItem.PSIsContainer){[IO.Path]::GetRelativePath($root,$file.FullName)}else{$file.Name}
                    [ordered]@{Path=$relative;Length=$file.Length;SHA256=(Get-SHA256 $file.FullName);Error=$null}
                }catch{[ordered]@{Path=$file.FullName;Length=$null;SHA256=$null;Error=$_.Exception.Message}}
            })
        }catch{$record.Error=$_.Exception.Message}
        $roots.Add([pscustomobject]$record)
    }
    return @($roots)
}
function Get-Snapshot([string]$Label){
    $status=Invoke-Step "$Label-git-status" "git" @("-c","core.quotepath=false","status","--porcelain=v1","--untracked-files=all","--no-renames")
    $head=Invoke-Step "$Label-git-head" "git" @("rev-parse","HEAD")
    $branch=Invoke-Step "$Label-git-branch" "git" @("branch","--show-current")
    $staged=Invoke-Step "$Label-git-staged" "git" @("diff","--cached","--name-only")
    if($status.ExitCode -ne 0 -or $head.ExitCode -ne 0 -or $branch.ExitCode -ne 0 -or $staged.ExitCode -ne 0){
        throw "Git snapshot inspection failed; see $LogsDir"
    }
    $delta=[Collections.Generic.List[object]]::new()
    foreach($line in @($status.Stdout -split "\r?\n"|Where-Object{$_})){
        if($line.Length -lt 4){continue};$relative=$line.Substring(3);$full=Join-Path $RepoRoot $relative
        try{$item=Get-Item -LiteralPath $full -ErrorAction Stop
            $delta.Add([pscustomobject][ordered]@{Status=$line.Substring(0,2);Path=$relative;
                Length=$item.Length;SHA256=(Get-SHA256 $full);Error=$null})
        }catch{$delta.Add([pscustomobject][ordered]@{Status=$line.Substring(0,2);Path=$relative;
                Length=$null;SHA256=$null;Error=$_.Exception.Message})}
    }
    $manifest=[ordered]@{Label=$Label;CreatedUtc=(Get-Date).ToUniversalTime().ToString("o");
        Branch=$branch.Stdout.Trim();Head=$head.Stdout.Trim();
        StagedPaths=@($staged.Stdout -split "\r?\n"|Where-Object{$_});
        Delta=@($delta);Protected=@(Get-ProtectedManifest)}
    $path=Join-Path $ReportsDir "$Label-snapshot-manifest.json"
    $manifest|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $path -Encoding utf8
    $fingerprint=Get-TextSHA256 (Get-ComparableManifest $manifest)
    return [pscustomobject]@{Data=$manifest;Path=$path;SHA256=$fingerprint;ManifestFileSHA256=(Get-SHA256 $path)}
}
function Get-ManifestErrors($Manifest){
    $errors=[Collections.Generic.List[string]]::new()
    foreach($item in $Manifest.Delta){if($item.Error){$errors.Add("$($item.Path): $($item.Error)")}}
    foreach($root in $Manifest.Protected){
        if($root.Error){$errors.Add("$($root.Root): $($root.Error)")}
        foreach($item in $root.Files){if($item.Error){$errors.Add("$($item.Path): $($item.Error)")}}
    };return @($errors)
}
function Get-ComparableManifest($Manifest){
    return([ordered]@{Branch=$Manifest.Branch;Head=$Manifest.Head;StagedPaths=$Manifest.StagedPaths;
        Delta=$Manifest.Delta;Protected=$Manifest.Protected}|ConvertTo-Json -Depth 10 -Compress)
}
function Read-ExternalEvidence([string]$Path,[string]$Kind,[string]$SnapshotSHA256){
    if(-not $Path){return $null}
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "Evidence file is missing: $Path"}
    $evidence=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json
    if($evidence.Kind -ne $Kind){throw "Evidence kind must be $Kind"}
    if($evidence.SnapshotSHA256 -ne $SnapshotSHA256){throw "Evidence snapshot hash does not match"}
    return $evidence
}
function Add-Tool([string]$Name,[string]$Path,[string]$Version){
    $hash=if($Path -and(Test-Path -LiteralPath $Path -PathType Leaf)){Get-SHA256 $Path}else{$null}
    $Tools.Add([pscustomobject][ordered]@{Name=$Name;Path=$Path;Version=$Version;SHA256=$hash})
}
function Write-Reports($StartSnapshot,$EndSnapshot){
    $finished=(Get-Date).ToUniversalTime()
    $summary=[ordered]@{SchemaVersion=1;Mode=$Mode;RunId=$RunId;RunDirectory=$RunDir;
        StartedUtc=$StartedUtc.ToString("o");FinishedUtc=$finished.ToString("o");
        DurationSeconds=[math]::Round(($finished-$StartedUtc).TotalSeconds,3);Repository=$RepoRoot;
        Snapshot=[ordered]@{StartManifest=$StartSnapshot.Path;StartManifestSHA256=$StartSnapshot.SHA256;
            EndManifest=$EndSnapshot.Path;EndManifestSHA256=$EndSnapshot.SHA256};
        Tools=@($Tools);Quick=$Quick;Gates=@($Gates.Values)}
    $jsonPath=Join-Path $ReportsDir "verification-summary.json"
    $summary|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $jsonPath -Encoding utf8
    Copy-Item -LiteralPath $jsonPath -Destination (Join-Path $EvidenceRoot "latest-summary.json") -Force
    $md=[Collections.Generic.List[string]]::new()
    $md.Add("# VMA release verification");$md.Add("")
    $md.Add("- Mode: $Mode");$md.Add("- Run: $RunId");$md.Add("- Snapshot: $($StartSnapshot.SHA256)");$md.Add("")
    $md.Add("| Gate | Status | Reason |");$md.Add("|---|---|---|")
    foreach($gate in $Gates.Values){
        $reason=(([string]$gate.Reason)-replace '[\r\n]',' ').Replace("|","\|")
        $md.Add("| $($gate.Id) - $($gate.Name) | **$($gate.Status)** | $reason |")
    }
    $md.Add("");$md.Add("## Evidence")
    foreach($gate in $Gates.Values){$md.Add("");$md.Add("### Gate $($gate.Id) - $($gate.Name)")
        foreach($check in $gate.Checks){$md.Add("- **$($check.Status)** $($check.Name): $($check.Reason) (exit: $($check.ExitCode), evidence: $($check.EvidencePath))")}
    }
    $markdownPath=Join-Path $ReportsDir "verification-report.md"
    $md|Set-Content -LiteralPath $markdownPath -Encoding utf8
    return [pscustomobject]@{Json=$jsonPath;Markdown=$markdownPath}
}

Write-Host "VMA verification: $Mode"
Write-Host "Evidence: $RunDir"
$GitPath=Get-ToolPath "git"
if(-not $GitPath){throw "Git is required"}
$gitVersion=Invoke-Step "tool-git-version" $GitPath @("--version")
Add-Tool "git" $GitPath $gitVersion.Stdout.Trim()
$StartSnapshot=Get-Snapshot "start"
$snapshotErrors=@(Get-ManifestErrors $StartSnapshot.Data)
if($StartSnapshot.Data.StagedPaths.Count -gt 0){Set-Gate A "FAIL" "Staged paths are present"}
elseif($snapshotErrors.Count -gt 0){Set-Gate A "BLOCKED" ("Hashing was incomplete: "+($snapshotErrors-join "; "))}
else{Set-Gate A "PASS" "Initial source and protected-path hashes were captured"}
Add-Check $Gates.A.Checks "Initial snapshot" $Gates.A.Status $Gates.A.Reason $null $StartSnapshot.Path

$PythonPath=Join-Path $RepoRoot ".venv\Scripts\python.exe"
if(-not(Test-Path -LiteralPath $PythonPath -PathType Leaf)){$PythonPath=Get-ToolPath "python"}
$NodePath=Get-ToolPath "node"
if($PythonPath){$v=Invoke-Step "tool-python-version" $PythonPath @("--version");Add-Tool "python" $PythonPath $v.Stdout.Trim()}
if($NodePath){$v=Invoke-Step "tool-node-version" $NodePath @("--version");Add-Tool "node" $NodePath $v.Stdout.Trim()}

if($Mode -eq "quick"){
    $problem=$false
    if($PythonPath){
        $step=Invoke-Step "quick-pip-check" $PythonPath @("-m","pip","check")
        $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"}
        Add-Check $Quick.Checks "pip check" $status "Existing environment only; not exact-lock evidence" $step
        if($status -ne "PASS"){$problem=$true}
        $step=Invoke-Step "quick-pytest" $PythonPath @("-m","pytest","-q",
            "--basetemp",(Join-Path $TempDir "pytest"),"-o","cache_dir=$(Join-Path $TempDir 'pytest-cache')","tests")
        $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"}
        Add-Check $Quick.Checks "pytest" $status "External pytest temporary directory" $step
        if($status -ne "PASS"){$problem=$true}
    }else{Add-Check $Quick.Checks "pytest" "BLOCKED" "Python is unavailable";$problem=$true}
    if($NodePath){
        $step=Invoke-Step "quick-node-check" $NodePath @("--check","frontend/js/app.js")
        $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"}
        Add-Check $Quick.Checks "JavaScript syntax" $status "node --check frontend/js/app.js" $step
        if($status -ne "PASS"){$problem=$true}
    }else{Add-Check $Quick.Checks "JavaScript syntax" "BLOCKED" "Node.js is unavailable";$problem=$true}
    $step=Invoke-Step "quick-git-diff-check" $GitPath @("diff","--check")
    $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"}
    Add-Check $Quick.Checks "git diff --check" $status "Whitespace-error check" $step
    if($status -ne "PASS"){$problem=$true}
    $Quick.Status=if($problem){"FAIL"}else{"PASS"}
    $Quick.Reason=if($problem){"At least one quick check failed or was blocked"}else{"All quick checks passed"}
    foreach($id in @("B","C","D","E","F","G")){Set-Gate $id "NOT_RUN" "Quick mode does not claim the full release gate"}
}else{
    $Previous=$null;$latestPath=Join-Path $EvidenceRoot "latest-summary.json"
    if($Mode -eq "resume" -and(Test-Path -LiteralPath $latestPath)){
        try{$Previous=Get-Content -LiteralPath $latestPath -Raw|ConvertFrom-Json}catch{$Previous=$null}
    }
    function Use-PreviousPass([string]$Id){
        if(-not $Previous){return $false}
        if($Previous.Snapshot.StartManifestSHA256 -ne $StartSnapshot.SHA256){return $false}
        $prior=$Previous.Gates|Where-Object Id -eq $Id|Select-Object -First 1
        if($prior -and $prior.Status -eq "PASS"){
            Set-Gate $Id "PASS" "Reused PASS from unchanged snapshot run $($Previous.RunId)"
            return $true
        };return $false
    }
    $Ffmpeg=$null
    if($FfmpegPath -and(Test-Path -LiteralPath $FfmpegPath -PathType Leaf)){$Ffmpeg=[IO.Path]::GetFullPath($FfmpegPath)}
    if(-not $Ffmpeg){$Ffmpeg=Get-ToolPath "ffmpeg"}
    $codecEnvironment=@{};if($Ffmpeg){$codecEnvironment["VMA_REAL_CODEC_FFMPEG"]=$Ffmpeg}

    if(-not(Use-PreviousPass B)){
        $blocked=$false;$failed=$false;$reuseWindows=$false
        if($Previous -and $Previous.Snapshot.StartManifestSHA256 -eq $StartSnapshot.SHA256){
            $priorB=$Previous.Gates|Where-Object Id -eq "B"|Select-Object -First 1
            $windowsNames=@("CPython 3.13 x86-64","Runtime hashed lock","Development hashed lock",
                "Runtime pip check","Development pip check","Full pytest suite","JavaScript syntax","git diff --check")
            if($priorB){
                $missing=@($windowsNames|Where-Object{
                    $name=$_; -not($priorB.Checks|Where-Object{$_.Name -eq $name -and $_.Status -eq "PASS"})
                })
                $reuseWindows=$missing.Count -eq 0
            }
        }
        if($reuseWindows){
            Add-Check $Gates.B.Checks "Windows exact-lock verification" "PASS" "Reused passed Windows components from $($Previous.RunId)" $null $latestPath
        }else{
        $PyLauncher=Get-ToolPath "py"
        if(-not $PyLauncher){Add-Check $Gates.B.Checks "CPython 3.13" "BLOCKED" "Python launcher unavailable";$blocked=$true}
        else{
            $identity=Invoke-Step "full-python-identity" $PyLauncher @("-3.13","-c","import json,platform,struct,sys;print(json.dumps({'version':sys.version,'bits':struct.calcsize('P')*8,'machine':platform.machine()}))")
            if($identity.ExitCode -ne 0 -or $identity.Stdout -notmatch '"bits": 64'){
                Add-Check $Gates.B.Checks "CPython 3.13 x86-64" "BLOCKED" "Required interpreter not confirmed" $identity;$blocked=$true
            }else{
                Add-Check $Gates.B.Checks "CPython 3.13 x86-64" "PASS" "Required interpreter confirmed" $identity
                $runtimeVenv=Join-Path $ArtifactsDir "venv-runtime";$devVenv=Join-Path $ArtifactsDir "venv-dev"
                $makeRuntime=Invoke-Step "full-create-runtime-venv" $PyLauncher @("-3.13","-m","venv",$runtimeVenv)
                $makeDev=Invoke-Step "full-create-dev-venv" $PyLauncher @("-3.13","-m","venv",$devVenv)
                if($makeRuntime.ExitCode -ne 0 -or $makeDev.ExitCode -ne 0){
                    Add-Check $Gates.B.Checks "Disposable environments" "FAIL" "Virtual environment creation failed" $makeDev;$failed=$true
                }elseif(-not $AllowNetwork -and -not $Wheelhouse){
                    Add-Check $Gates.B.Checks "Hashed lock installation" "BLOCKED" "Supply -AllowNetwork or approved -Wheelhouse";$blocked=$true
                }else{
                    $runtimePython=Join-Path $runtimeVenv "Scripts\python.exe";$devPython=Join-Path $devVenv "Scripts\python.exe"
                    $install=@("-m","pip","install","--disable-pip-version-check")
                    if($Wheelhouse){
                        if(-not(Test-Path -LiteralPath $Wheelhouse -PathType Container)){throw "Wheelhouse not found: $Wheelhouse"}
                        $install+=@("--no-index","--find-links",[IO.Path]::GetFullPath($Wheelhouse))
                    }
                    $ri=Invoke-Step "full-runtime-lock-install" $runtimePython ($install+@("-r",(Join-Path $RepoRoot "requirements.lock")))
                    $di=Invoke-Step "full-dev-lock-install" $devPython ($install+@("-r",(Join-Path $RepoRoot "requirements-dev.lock")))
                    foreach($pair in @(@("Runtime hashed lock",$ri),@("Development hashed lock",$di))){
                        $status=if($pair[1].ExitCode -eq 0){"PASS"}else{"FAIL"}
                        Add-Check $Gates.B.Checks $pair[0] $status "Hash-locked wheel installation" $pair[1]
                        if($status -ne "PASS"){$failed=$true}
                    }
                    if(-not $failed){
                        foreach($pair in @(
                            @("Runtime pip check",(Invoke-Step "full-runtime-pip-check" $runtimePython @("-m","pip","check"))),
                            @("Development pip check",(Invoke-Step "full-dev-pip-check" $devPython @("-m","pip","check"))),
                            @("Full pytest suite",(Invoke-Step "full-pytest" $devPython @("-m","pytest","-q",
                                "--basetemp",(Join-Path $TempDir "pytest"),"-o","cache_dir=$(Join-Path $TempDir 'pytest-cache')","tests") $RepoRoot $codecEnvironment))
                        )){
                            $status=if($pair[1].ExitCode -eq 0){"PASS"}else{"FAIL"}
                            Add-Check $Gates.B.Checks $pair[0] $status "Clean CPython 3.13 environment" $pair[1]
                            if($status -ne "PASS"){$failed=$true}
                        }
                    }
                }
            }
        }
        if($NodePath){$step=Invoke-Step "full-node-check" $NodePath @("--check","frontend/js/app.js")
            $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"};Add-Check $Gates.B.Checks "JavaScript syntax" $status "node --check" $step
            if($status -ne "PASS"){$failed=$true}
        }else{Add-Check $Gates.B.Checks "JavaScript syntax" "BLOCKED" "Node.js unavailable";$blocked=$true}
        $step=Invoke-Step "full-git-diff-check" $GitPath @("diff","--check")
        $status=if($step.ExitCode -eq 0){"PASS"}else{"FAIL"};Add-Check $Gates.B.Checks "git diff --check" $status "Whitespace check" $step
        if($status -ne "PASS"){$failed=$true}
        }
        try{$linux=Read-ExternalEvidence $LinuxEvidencePath "vma-linux-lock-verification" $StartSnapshot.SHA256
            if($linux -and $linux.Status -eq "PASS"){Add-Check $Gates.B.Checks "Linux exact lock" "PASS" "Matching evidence" $null $LinuxEvidencePath}
            else{Add-Check $Gates.B.Checks "Linux exact lock" "BLOCKED" "No authorized Linux evidence";$blocked=$true}
        }catch{Add-Check $Gates.B.Checks "Linux exact lock" "FAIL" $_.Exception.Message $null $LinuxEvidencePath;$failed=$true}
        if($failed){Set-Gate B "FAIL" "One or more test/install checks failed"}
        elseif($blocked){Set-Gate B "BLOCKED" "Required exact-lock evidence incomplete"}
        else{Set-Gate B "PASS" "Windows and Linux exact-lock tests passed"}
    }

    if(-not(Use-PreviousPass C)){
        if(-not $Ffmpeg){
            Set-Gate C "BLOCKED" "No approved FFmpeg executable found or supplied"
            Add-Check $Gates.C.Checks "FFmpeg discovery" "BLOCKED" $Gates.C.Reason
        }else{
            $ffprobe=Join-Path (Split-Path -Parent $Ffmpeg) "ffprobe.exe"
            if(-not(Test-Path -LiteralPath $ffprobe -PathType Leaf)){
                Set-Gate C "BLOCKED" "Colocated ffprobe.exe is missing"
                Add-Check $Gates.C.Checks "FFprobe discovery" "BLOCKED" $Gates.C.Reason
            }else{
                $fv=Invoke-Step "codec-ffmpeg-version" $Ffmpeg @("-version")
                $pv=Invoke-Step "codec-ffprobe-version" $ffprobe @("-version")
                Add-Tool "ffmpeg" $Ffmpeg (($fv.Stdout -split "\r?\n")[0])
                Add-Tool "ffprobe" $ffprobe (($pv.Stdout -split "\r?\n")[0])
                $codecPython=$null;$codecCandidates=[Collections.Generic.List[string]]::new()
                $codecCandidates.Add((Join-Path $ArtifactsDir "venv-dev\Scripts\python.exe"))
                if($Previous){$codecCandidates.Add((Join-Path $Previous.RunDirectory "artifacts\venv-dev\Scripts\python.exe"))}
                if($PythonPath){$codecCandidates.Add($PythonPath)}
                $candidateNumber=0
                foreach($candidate in $codecCandidates){
                    $candidateNumber++
                    if(-not(Test-Path -LiteralPath $candidate -PathType Leaf)){continue}
                    $probe=Invoke-Step "codec-python-probe-$candidateNumber" $candidate @("-c","import pytest")
                    if($probe.ExitCode -eq 0){$codecPython=$candidate;break}
                }
                if(-not $codecPython){Set-Gate C "BLOCKED" "No Python environment available"}
                else{
                    $step=Invoke-Step "codec-four-cases" $codecPython @("-m","pytest","-q","--basetemp",
                        (Join-Path $TempDir "codec-pytest"),"-o","cache_dir=$(Join-Path $TempDir 'codec-pytest-cache')",
                        "tests/test_vma_real_codec_fixtures.py") $RepoRoot @{VMA_REAL_CODEC_FFMPEG=$Ffmpeg}
                    if($step.ExitCode -eq 0 -and $step.Stdout -match '4 passed' -and $step.Stdout -notmatch 'skipped'){
                        Set-Gate C "PASS" "All four real-codec cases passed without skips"
                        Add-Check $Gates.C.Checks "Four real codecs" "PASS" $Gates.C.Reason $step
                    }else{
                        Set-Gate C "FAIL" "Codec run did not produce four non-skipped passes"
                        Add-Check $Gates.C.Checks "Four real codecs" "FAIL" $Gates.C.Reason $step
                    }
                }
            }
        }
    }

    $ImageDigest=$null;$ImageId=$null;$ImageReference="vma-verification:$($RunId.ToLowerInvariant())"
    $ContainerReused=$false
    if($Previous){$ContainerReused=Use-PreviousPass D}
    if($ContainerReused){
        $priorBinding=Join-Path $Previous.RunDirectory "reports\container-image-binding.json"
        try{
            $binding=Get-Content -LiteralPath $priorBinding -Raw|ConvertFrom-Json
            $DockerPath=Get-ToolPath "docker"
            $inspect=if($DockerPath){Invoke-Step "docker-reused-image" $DockerPath @("image","inspect","--format","{{.Id}}",[string]$binding.ImageId)}else{$null}
            if($inspect -and $inspect.ExitCode -eq 0 -and $inspect.Stdout.Trim() -eq [string]$binding.ImageId){
                $ImageDigest=[string]$binding.ImageDigest;$ImageId=[string]$binding.ImageId;$ImageReference=[string]$binding.ImageReference
                Add-Check $Gates.D.Checks "Reused immutable image" "PASS" "Local image identity matches prior PASS evidence" $inspect $priorBinding
            }else{
                Set-Gate D "BLOCKED" "Prior container PASS cannot be reused because the exact local image is unavailable"
                Add-Check $Gates.D.Checks "Reused immutable image" "BLOCKED" $Gates.D.Reason $inspect $priorBinding
            }
        }catch{
            Set-Gate D "BLOCKED" "Prior container image binding is unavailable or unreadable"
            Add-Check $Gates.D.Checks "Reused immutable image" "BLOCKED" $Gates.D.Reason $null $priorBinding
        }
    }
    if(-not $ContainerReused){
        $DockerPath=Get-ToolPath "docker"
        if(-not $DockerPath){
            Set-Gate D "BLOCKED" "Docker/Podman is not installed or available"
            Add-Check $Gates.D.Checks "Container engine" "BLOCKED" $Gates.D.Reason
        }else{
            $version=Invoke-Step "docker-version" $DockerPath @("version","--format","{{json .}}")
            if($version.ExitCode -ne 0){
                Set-Gate D "BLOCKED" "Docker CLI exists but its engine is unavailable"
                Add-Check $Gates.D.Checks "Docker engine" "BLOCKED" $Gates.D.Reason $version
            }else{
                Add-Tool "docker" $DockerPath "See docker-version.log"
                $base="python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f"
                $cached=Invoke-Step "docker-base-cache" $DockerPath @("image","inspect",$base)
                if(-not $AllowNetwork -and $cached.ExitCode -ne 0){
                    Set-Gate D "BLOCKED" "Pinned base image is not cached and network was not authorized"
                    Add-Check $Gates.D.Checks "Pinned base image" "BLOCKED" $Gates.D.Reason $cached
                }else{
                    $metadataPath=Join-Path $ArtifactsDir "build-metadata.json"
                    $build=Invoke-Step "docker-build" $DockerPath @("buildx","build","--load","--metadata-file",$metadataPath,
                        "-t",$ImageReference,".")
                    if($build.ExitCode -ne 0){
                        Set-Gate D "FAIL" "Docker image build failed"
                        Add-Check $Gates.D.Checks "Image build" "FAIL" $Gates.D.Reason $build
                    }else{
                        if(Test-Path -LiteralPath $metadataPath){
                            $metadata=Get-Content -LiteralPath $metadataPath -Raw|ConvertFrom-Json
                            $property=$metadata.PSObject.Properties["containerimage.digest"]
                            if($property){$ImageDigest=[string]$property.Value}
                        }
                        $identity=Invoke-Step "docker-image-identity" $DockerPath @("image","inspect","--format","{{.Id}}",$ImageReference)
                        if($identity.ExitCode -eq 0){$ImageId=$identity.Stdout.Trim()}
                        $bindingPath=Join-Path $ReportsDir "container-image-binding.json"
                        [ordered]@{ImageReference=$ImageReference;ImageDigest=$ImageDigest;ImageId=$ImageId;BuildMetadata=$metadataPath}|
                            ConvertTo-Json|Set-Content -LiteralPath $bindingPath -Encoding utf8
                        $identityPass=$ImageDigest -match '^sha256:[0-9a-f]{64}$' -and $ImageId -match '^sha256:[0-9a-f]{64}$'
                        Add-Check $Gates.D.Checks "Image build and identity" $(if($identityPass){"PASS"}else{"FAIL"}) "Manifest digest and immutable local image ID required" $identity $bindingPath
                        $runReference=if($ImageId){$ImageId}else{$ImageReference}
                        $negative=Invoke-Step "docker-fail-closed" $DockerPath @("run","--rm",$runReference)
                        $negativePass=$negative.ExitCode -ne 0 -and($negative.Stdout+$negative.Stderr) -match 'VMA_TRUSTED_HOSTS|VMA_ALLOWED_ORIGINS|VMA_HEALTHCHECK_HOST'
                        $status=if($negativePass){"PASS"}else{"FAIL"}
                        Add-Check $Gates.D.Checks "Missing production configuration" $status "Must fail closed" $negative
                        $name="vma-verify-"+($RunId -replace '[^a-zA-Z0-9]','').ToLowerInvariant()
                        $run=Invoke-Step "docker-production-start" $DockerPath @("run","--rm","-d","--name",$name,
                            "--read-only","--cap-drop=ALL","--security-opt=no-new-privileges:true",
                            "--tmpfs","/tmp/vma:rw,noexec,nosuid,size=8g","-p","127.0.0.1::8000",
                            "-e","VMA_ENVIRONMENT=production","-e","VMA_TRUSTED_HOSTS=audio.example.test",
                            "-e","VMA_ALLOWED_ORIGINS=https://audio.example.test","-e","VMA_HEALTHCHECK_HOST=audio.example.test",$runReference)
                        if($run.ExitCode -ne 0){
                            Set-Gate D "FAIL" "Production container did not start"
                            Add-Check $Gates.D.Checks "Production startup" "FAIL" $Gates.D.Reason $run
                        }else{
                            try{
                                $healthy=$false
                                for($attempt=0;$attempt -lt 30;$attempt++){
                                    Start-Sleep -Seconds 2
                                    $health=Invoke-Step "docker-health-$attempt" $DockerPath @("inspect","--format","{{.State.Health.Status}}",$name)
                                    if($health.ExitCode -eq 0 -and $health.Stdout.Trim() -eq "healthy"){$healthy=$true;break}
                                }
                                $user=Invoke-Step "docker-user" $DockerPath @("image","inspect","--format","{{.Config.User}}",$runReference)
                                $userPass=$user.ExitCode -eq 0 -and $user.Stdout.Trim() -eq "vma"
                                $port=Invoke-Step "docker-port" $DockerPath @("port",$name,"8000/tcp")
                                $portMatch=[regex]::Match($port.Stdout,'(?m):(\d+)\s*$')
                                $smokePass=$false;$smoke=$port
                                if($healthy -and $port.ExitCode -eq 0 -and $portMatch.Success -and $PythonPath){
                                    $smokeCode=@'
import http.client, json, sys
port = int(sys.argv[1])
def request(method, path, host="audio.example.test", origin=None):
    headers = {"Host": host}
    if origin: headers["Origin"] = origin
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(method, path, body=b"" if method == "POST" else None, headers=headers)
    response = connection.getresponse()
    body = response.read()
    headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, headers, body
status, headers, body = request("GET", "/api/health")
assert status == 200 and json.loads(body) == {"status": "ok"}
required = {"content-security-policy": lambda value: value.startswith("default-src 'self'"), "x-content-type-options": lambda value: value == "nosniff", "x-frame-options": lambda value: value == "DENY", "referrer-policy": lambda value: value == "no-referrer", "strict-transport-security": lambda value: value.startswith("max-age="), "x-request-id": bool}
assert all(check(headers.get(name, "")) for name, check in required.items())
status, _, body = request("GET", "/api/ready")
assert status == 200 and json.loads(body) == {"status": "ready"}
status, _, body = request("GET", "/api/health", host="hostile.example")
assert status == 400 and json.loads(body) == {"detail": "invalid host header"}
for path, expected in (("/docs", 404), ("/redoc", 404), ("/openapi.json", 200)):
    assert request("GET", path)[0] == expected
status, headers, _ = request("POST", "/api/demo", origin="https://audio.example.test")
cookie = headers.get("set-cookie", "").lower()
assert status == 200 and all(value in cookie for value in ("httponly", "secure", "samesite=strict", "path=/api"))
print("container HTTP security smoke PASS")
'@
                                    $smoke=Invoke-Step "docker-http-security-smoke" $PythonPath @("-c",$smokeCode,$portMatch.Groups[1].Value)
                                    $smokePass=$smoke.ExitCode -eq 0
                                }
                                $healthStatus=if($healthy){"PASS"}else{"FAIL"}
                                $userStatus=if($userPass){"PASS"}else{"FAIL"}
                                $smokeStatus=if($smokePass){"PASS"}else{"FAIL"}
                                Add-Check $Gates.D.Checks "Container health" $healthStatus "Must become healthy" $health
                                Add-Check $Gates.D.Checks "Non-root runtime" $userStatus "Image user must be vma" $user
                                Add-Check $Gates.D.Checks "Production HTTP security smoke" $smokeStatus "Host policy, liveness/readiness, security headers/HSTS, docs/OpenAPI, and session cookie" $smoke
                                if($negativePass -and $identityPass -and $healthy -and $userPass -and $smokePass){
                                    Set-Gate D "PASS" "Immutable image build, least-privilege startup, production HTTP security, and fail-closed checks passed"
                                }else{Set-Gate D "FAIL" "A container assertion failed or image digest is missing"}
                            }finally{[void](Invoke-Step "docker-cleanup" $DockerPath @("rm","-f",$name))}
                        }
                    }
                }
            }
        }
    }

    if(-not(Use-PreviousPass E)){
        try{
            $browser=Read-ExternalEvidence $BrowserEvidencePath "vma-browser-acceptance" $StartSnapshot.SHA256
            if($browser -and $browser.Chrome.Status -eq "PASS" -and $browser.Edge.Status -eq "PASS"){
                Set-Gate E "PASS" "Matching Chrome and Edge evidence supplied"
                Add-Check $Gates.E.Checks "Chrome and Edge" "PASS" $Gates.E.Reason $null $BrowserEvidencePath
            }else{
                Set-Gate E "BLOCKED" "Matching PASS evidence for Chrome and Edge unavailable"
                Add-Check $Gates.E.Checks "Chrome and Edge" "BLOCKED" $Gates.E.Reason
            }
        }catch{Set-Gate E "FAIL" $_.Exception.Message;Add-Check $Gates.E.Checks "Browser evidence" "FAIL" $Gates.E.Reason $null $BrowserEvidencePath}
    }

    if(-not(Use-PreviousPass F)){
        $blocked=$false;$failed=$false;$pipAudit=Get-ToolPath "pip-audit"
        if(-not $pipAudit){
            Add-Check $Gates.F.Checks "Python vulnerability scan" "BLOCKED" "Verified pip-audit unavailable";$blocked=$true
        }else{
            $ra=Invoke-Step "pip-audit-runtime" $pipAudit @("-r","requirements.lock","--format","json","--output",(Join-Path $ReportsDir "runtime-vulnerabilities.json"))
            $da=Invoke-Step "pip-audit-development" $pipAudit @("-r","requirements-dev.lock","--format","json","--output",(Join-Path $ReportsDir "development-vulnerabilities.json"))
            foreach($pair in @(@("Runtime dependencies",$ra),@("Development dependencies",$da))){
                $status=if($pair[1].ExitCode -eq 0){"PASS"}else{"FAIL"}
                Add-Check $Gates.F.Checks $pair[0] $status "Current advisory scan" $pair[1]
                if($status -ne "PASS"){$failed=$true}
            }
        }
        $trivy=Get-ToolPath "trivy";$syft=Get-ToolPath "syft"
        if($Gates.D.Status -ne "PASS" -or -not $ImageDigest -or -not $ImageId){
            Add-Check $Gates.F.Checks "Image scan and SBOM" "BLOCKED" "Gate D did not provide tested image digest";$blocked=$true
        }elseif(-not $trivy -or -not $syft){
            Add-Check $Gates.F.Checks "Image scan and SBOM" "BLOCKED" "Verified Trivy and Syft required";$blocked=$true
        }else{
            $imageReport=Join-Path $ReportsDir "image-vulnerabilities.json";$sbomPath=Join-Path $ReportsDir "image.spdx.json"
            $trivyVersion=Invoke-Step "trivy-version" $trivy @("version","--format","json")
            $syftVersion=Invoke-Step "syft-version" $syft @("version")
            Add-Tool "trivy" $trivy "See trivy-version.log";Add-Tool "syft" $syft "See syft-version.log"
            $scan=Invoke-Step "trivy-image" $trivy @("image","--scanners","vuln","--format","json","--output",$imageReport,$ImageId)
            $gateScan=Invoke-Step "trivy-high-critical" $trivy @("image","--scanners","vuln","--severity","HIGH,CRITICAL","--exit-code","1",$ImageId)
            $dbMetadata=Invoke-Step "trivy-db-metadata" $trivy @("version","--format","json")
            $sbom=Invoke-Step "syft-sbom" $syft @("docker:$ImageId","-o","spdx-json=$sbomPath")
            $bindingPath=Join-Path $ReportsDir "image-sbom-binding.json"
            [ordered]@{ImageReference=$ImageReference;ImageDigest=$ImageDigest;ImageId=$ImageId;ScannedImageId=$ImageId;SBOM=$sbomPath;
                SBOMSHA256=if(Test-Path -LiteralPath $sbomPath){Get-SHA256 $sbomPath}else{$null}}|
                ConvertTo-Json|Set-Content -LiteralPath $bindingPath -Encoding utf8
            $dbCurrent=$dbMetadata.ExitCode -eq 0 -and $dbMetadata.Stdout -match 'DownloadedAt'
            $sbomValid=$false
            try{$spdx=Get-Content -LiteralPath $sbomPath -Raw|ConvertFrom-Json;$sbomValid=$spdx.spdxVersion -match '^SPDX-' -and [bool]$spdx.documentNamespace -and @($spdx.packages).Count -gt 0}catch{$sbomValid=$false}
            $pass=$scan.ExitCode -eq 0 -and $gateScan.ExitCode -eq 0 -and $sbom.ExitCode -eq 0 -and $sbomValid
            $status=if($pass){"PASS"}else{"FAIL"}
            Add-Check $Gates.F.Checks "Image vulnerability scan" $status "Exact image; zero High/Critical findings" $gateScan
            Add-Check $Gates.F.Checks "Trivy advisory database" $(if($dbCurrent){"PASS"}else{"BLOCKED"}) "Database timestamp retained in trivy-db-metadata.log" $dbMetadata
            Add-Check $Gates.F.Checks "SPDX SBOM" $(if($sbomValid -and $sbom.ExitCode -eq 0){"PASS"}else{"FAIL"}) "Validated SPDX document; digest binding: $bindingPath" $sbom
            if(-not $dbCurrent){$blocked=$true}
            if(-not $pass){$failed=$true}
        }
        if($failed){Set-Gate F "FAIL" "At least one required security scan failed"}
        elseif($blocked){Set-Gate F "BLOCKED" "Scanner, advisory data, image digest, or SBOM unavailable"}
        else{Set-Gate F "PASS" "Dependency/image scans and digest-bound SBOM passed"}
    }

    if(-not(Use-PreviousPass G)){
        $workflowPath=Join-Path $RepoRoot ".github\workflows\ci.yml"
        $workflow=Get-Content -LiteralPath $workflowPath -Raw
        if($workflow.Contains("requirements-dev.lock") -and $workflow.Contains("windows-latest") -and
           $workflow.Contains("runner.temp") -and $workflow.Contains("--basetemp")){
            Set-Gate G "PASS" "Exact-lock Windows/Linux CI configuration present; external CI not contacted"
            Add-Check $Gates.G.Checks "CI configuration" "PASS" $Gates.G.Reason $null $workflowPath
        }else{
            Set-Gate G "BLOCKED" "Exact-lock Windows/Linux CI safeguards incomplete"
            Add-Check $Gates.G.Checks "CI configuration" "BLOCKED" $Gates.G.Reason $null $workflowPath
        }
    }
}

$EndSnapshot=Get-Snapshot "end"
$same=(Get-ComparableManifest $StartSnapshot.Data) -ceq (Get-ComparableManifest $EndSnapshot.Data)
if(-not $same){
    Set-Gate A "FAIL" "Repository or protected-path state changed during verification"
    Add-Check $Gates.A.Checks "Final integrity comparison" "FAIL" $Gates.A.Reason $null $EndSnapshot.Path
}elseif($Gates.A.Status -eq "PASS"){
    Set-Gate A "PASS" "Repository and protected-path manifests unchanged during verification"
    Add-Check $Gates.A.Checks "Final integrity comparison" "PASS" $Gates.A.Reason $null $EndSnapshot.Path
}else{
    Add-Check $Gates.A.Checks "Final integrity comparison" $Gates.A.Status "State stable, but initial hashing incomplete" $null $EndSnapshot.Path
}
$Report=Write-Reports $StartSnapshot $EndSnapshot
Write-Host "Markdown report: $($Report.Markdown)"
Write-Host "JSON summary: $($Report.Json)"
$required=if($Mode -eq "quick"){@($Gates.A.Status,$Quick.Status)}else{@($Gates.Values|ForEach-Object Status)}
if(@($required|Where-Object{$_ -ne "PASS"}).Count -gt 0){exit 2}
exit 0
