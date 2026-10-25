param(
    [switch]$Apply,
    [ValidateRange(7, 3650)][int]$MinimumAgeDays = 7,
    [string]$EvidenceDirectory = (Join-Path $PSScriptRoot 'private')
)
$ErrorActionPreference = 'Stop'
$taskLocalBase = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
$taskCutoff = [DateTime]::UtcNow.AddDays(-$MinimumAgeDays)
$taskSpecs = @(
    @{ Name = 'pip HTTP缓存'; Relative = 'pip\Cache\http-v2'; TempOnly = $false },
    @{ Name = 'pip wheel缓存'; Relative = 'pip\Cache\wheels'; TempOnly = $false },
    @{ Name = 'npm包下载缓存'; Relative = 'npm-cache\_cacache'; TempOnly = $false },
    @{ Name = '过期tmp文件'; Relative = 'Temp'; TempOnly = $true }
)
$taskDriveBefore = [IO.DriveInfo]::new('C:\').AvailableFreeSpace
$taskRows = [Collections.Generic.List[object]]::new()
$taskSkipped = 0
function Test-TaskPath([string]$Path, [string]$Root) {
    $taskCanonical = [IO.Path]::GetFullPath($Path)
    $taskPrefix = $Root.TrimEnd('\') + '\'
    if (-not $taskCanonical.StartsWith($taskPrefix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    $taskProbe = Get-Item -LiteralPath $taskCanonical -Force -ErrorAction Stop
    while ($null -ne $taskProbe) {
        if (($taskProbe.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
        if ($taskProbe.FullName.TrimEnd('\') -ieq $taskLocalBase.TrimEnd('\')) { return $true }
        $taskProbe = if ($taskProbe -is [IO.DirectoryInfo]) { $taskProbe.Parent } else { $taskProbe.Directory }
    }
    return $false
}
foreach ($taskSpec in $taskSpecs) {
    $taskRoot = [IO.Path]::GetFullPath((Join-Path $taskLocalBase $taskSpec.Relative))
    if (-not $taskRoot.StartsWith($taskLocalBase.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Root escaped LocalAppData' }
    if (-not (Test-Path -LiteralPath $taskRoot -PathType Container)) { continue }
    $taskRootItem = Get-Item -LiteralPath $taskRoot -Force
    if (($taskRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing reparse root: $taskRoot" }
    $taskQueue = [Collections.Generic.Stack[string]]::new()
    $taskQueue.Push($taskRoot)
    while ($taskQueue.Count -gt 0) {
        $taskDirectory = $taskQueue.Pop()
        try { $taskChildren = Get-ChildItem -LiteralPath $taskDirectory -Force -ErrorAction Stop } catch { $taskSkipped++; continue }
        foreach ($taskItem in $taskChildren) {
            if (($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $taskSkipped++; continue }
            if ($taskItem.PSIsContainer) { $taskQueue.Push($taskItem.FullName); continue }
            if ($taskItem.LastWriteTimeUtc -ge $taskCutoff) { continue }
            if ($taskSpec.TempOnly -and $taskItem.Extension -ine '.tmp') { continue }
            $taskRow = [ordered]@{ Category=$taskSpec.Name; Path=$taskItem.FullName; Bytes=[long]$taskItem.Length; LastWriteUtc=$taskItem.LastWriteTimeUtc.ToString('o'); Status='Candidate'; Error='' }
            if ($Apply) {
                try {
                    if (-not (Test-TaskPath -Path $taskItem.FullName -Root $taskRoot)) { throw 'Unsafe or reparse path' }
                    $taskCurrent = Get-Item -LiteralPath $taskItem.FullName -Force
                    if ($taskCurrent.LastWriteTimeUtc -ge $taskCutoff) { throw 'File became recent' }
                    $taskExclusive = [IO.File]::Open($taskCurrent.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
                    $taskExclusive.Dispose()
                    Remove-Item -LiteralPath $taskCurrent.FullName -Force -ErrorAction Stop
                    if (Test-Path -LiteralPath $taskCurrent.FullName) { throw 'File still present after removal' }
                    $taskRow.Status = 'Deleted'
                } catch { $taskRow.Status = 'Skipped'; $taskRow.Error = $_.Exception.Message }
            }
            $taskRows.Add([pscustomobject]$taskRow)
        }
    }
}
$taskDriveAfter = [IO.DriveInfo]::new('C:\').AvailableFreeSpace
$taskSummary = @($taskRows | Group-Object Category | ForEach-Object {
    $taskDeleted = @($_.Group | Where-Object Status -eq 'Deleted')
    [pscustomobject]@{ Category=$_.Name; Candidates=$_.Count; CandidateBytes=[long](($_.Group | Measure-Object Bytes -Sum).Sum); DeletedFiles=$taskDeleted.Count; DeletedBytes=[long](($taskDeleted | Measure-Object Bytes -Sum).Sum); SkippedFiles=@($_.Group | Where-Object Status -eq 'Skipped').Count }
})
$taskResult = [ordered]@{ CapturedAt=[DateTimeOffset]::Now.ToString('o'); Applied=[bool]$Apply; MinimumAgeDays=$MinimumAgeDays; AllowedRoots=@($taskSpecs | ForEach-Object { Join-Path $taskLocalBase $_.Relative }); DriveTotalBytes=[IO.DriveInfo]::new('C:\').TotalSize; FreeBeforeBytes=$taskDriveBefore; FreeAfterBytes=$taskDriveAfter; FreeDeltaBytes=$taskDriveAfter-$taskDriveBefore; DeletedBytes=[long](($taskRows | Where-Object Status -eq 'Deleted' | Measure-Object Bytes -Sum).Sum); EnumerationSkipped=$taskSkipped; Categories=$taskSummary }
New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$taskMode = if ($Apply) { 'apply' } else { 'preview' }
$taskJsonPath = Join-Path $EvidenceDirectory "$taskStamp-$taskMode-summary.json"
$taskCsvPath = Join-Path $EvidenceDirectory "$taskStamp-$taskMode-files.csv"
$taskResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $taskJsonPath -Encoding utf8
$taskRows | Export-Csv -LiteralPath $taskCsvPath -NoTypeInformation -Encoding utf8
$taskResult | ConvertTo-Json -Depth 6
Write-Output "Evidence: $taskJsonPath"
Write-Output "Manifest: $taskCsvPath"
