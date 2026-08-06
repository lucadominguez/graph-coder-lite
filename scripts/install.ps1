param(
  [switch]$DryRun,
  [switch]$RemoveRetired,
  [string]$ProjectRoot = (Get-Location).Path,
  [string]$Dest = ".agents/skills"
)
$ErrorActionPreference = "Stop"
$Skills = @("graph-coder-lite", "gcl-plan", "gcl-review")
# Graph Coder's skills describe a ten-phase lifecycle this one replaced. Both
# sets installed together offer the same phases under different names, and a run
# can select either.
$Retired = @{
  "graph-coder"        = "graph-coder-lite"
  "plan-forge"         = "gcl-plan"
  "execution-manager"  = "gcl-review"
  "plan-rehearsal"     = "(removed: there is no rehearsal phase)"
  "concept-grill"      = "(merged into the GROUND phase)"
  "technical-research" = "(merged into the PLAN phase)"
  "delegation-graph"   = "(the plan file is the graph)"
  "routing-plan"       = "(use gcl route set)"
}
$SourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../skills"))
$DestinationRoot = if ([System.IO.Path]::IsPathRooted($Dest)) { $Dest } else { Join-Path $ProjectRoot $Dest }

function Ensure-Directory([string]$Path) {
  if ($DryRun) { Write-Output "DRY RUN mkdir $Path"; return }
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
  }
}

function Copy-Skill([string]$Source, [string]$Target) {
  if (-not (Test-Path -LiteralPath (Join-Path $Source "SKILL.md"))) {
    throw "Invalid skill source: $Source"
  }
  if ($DryRun) { Write-Output "DRY RUN copy $Source -> $Target"; return }
  Ensure-Directory $Target
  Copy-Item -Path (Join-Path $Source "*") -Destination $Target -Recurse -Force
}

function Report-Retired([string]$Root) {
  foreach ($Name in $Retired.Keys) {
    $Path = Join-Path $Root $Name
    if (-not (Test-Path -LiteralPath (Join-Path $Path "SKILL.md"))) { continue }
    if ($RemoveRetired) {
      if ($DryRun) { Write-Output "DRY RUN remove superseded skill $Path" }
      else {
        Remove-Item -LiteralPath $Path -Recurse -Force
        Write-Output "REMOVED superseded skill $Path"
      }
    }
    else {
      Write-Warning "Full Graph Coder skill still installed: $Path. It shadows $($Retired[$Name]) and a run can select it instead. Keep it deliberately, or re-run with -RemoveRetired."
    }
  }
}

Ensure-Directory $DestinationRoot
foreach ($Skill in $Skills) {
  Copy-Skill (Join-Path $SourceRoot $Skill) (Join-Path $DestinationRoot $Skill)
}
Report-Retired $DestinationRoot
Write-Output "Graph Coder Lite skills installed idempotently for PowerShell 5.1+. No secrets read or written."
