$ErrorActionPreference = 'Stop'

$ToolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebsiteInstaller = Join-Path $ToolDir 'Install-GMCommandToolWebsite.ps1'

& $WebsiteInstaller
