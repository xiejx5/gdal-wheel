$ErrorActionPreference = 'Stop'
$lock = Get-Content "$PSScriptRoot/dependencies.json" | ConvertFrom-Json
$root = Split-Path $PSScriptRoot
function Run-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Command" }
}
Run-Checked { git -C $env:VCPKG_INSTALLATION_ROOT fetch origin $lock.vcpkg_baseline --depth=1 }
Run-Checked { git -C $env:VCPKG_INSTALLATION_ROOT checkout --detach $lock.vcpkg_baseline }
Run-Checked { & "$env:VCPKG_INSTALLATION_ROOT/bootstrap-vcpkg.bat" -disableMetrics }
Run-Checked { & "$env:VCPKG_INSTALLATION_ROOT/vcpkg.exe" install --triplet=x64-windows "--x-manifest-root=$PSScriptRoot" "--x-install-root=$root/build/vcpkg_installed" "--overlay-triplets=$PSScriptRoot/triplets" }
$installed = "$root/build/vcpkg_installed/x64-windows"
New-Item -ItemType Directory -Force $env:BUILD_PREFIX | Out-Null
foreach ($dir in @('bin', 'lib', 'include', 'share')) {
    New-Item -ItemType Directory -Force "$env:BUILD_PREFIX/$dir" | Out-Null
    Copy-Item -Recurse -Force "$installed/$dir/*" "$env:BUILD_PREFIX/$dir"
}
New-Item -ItemType Directory -Force "$env:BUILD_PREFIX/share/licenses" | Out-Null
Get-ChildItem "$installed/share/*/copyright" | ForEach-Object {
    Copy-Item $_.FullName "$env:BUILD_PREFIX/share/licenses/$($_.Directory.Name).txt"
}
Run-Checked { python "$PSScriptRoot/build-native.py" }
