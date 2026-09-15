# Superseded by build.ps1 (tests, exe, frozen self-test, portable zip, installer).
# Kept so older instructions that mention this script still work.
& (Join-Path $PSScriptRoot "build.ps1") @args
exit $LASTEXITCODE
