function Deploy-Latest {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [string] $Dest = "."
    )
    # find the newest file in Downloads matching "<Name>*.py" (handles the
    # "name (3).py" duplicates the browser creates), copy it to $Dest, and
    # report the real source name + byte count so you can verify on-disk.
    $src = Get-ChildItem "$env:USERPROFILE\Downloads\$Name*.py" |
           Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $src) {
        Write-Host "No '$Name*.py' found in Downloads." -ForegroundColor Red
        return
    }
    if ($Dest -eq ".") { $Dest = (Get-Location).Path }
    $target = Join-Path $Dest "$Name.py"
    Copy-Item $src.FullName $target -Force
    $bytes = (Get-Item $target).Length
    Write-Host "deployed $($src.Name) -> $target  ($bytes bytes)" -ForegroundColor Green
}
