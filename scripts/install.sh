#!/usr/bin/env sh
set -eu
DRY_RUN=0
REMOVE_RETIRED=0
PROJECT_ROOT="$(pwd)"
DEST=".agents/skills"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../skills" && pwd)

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --remove-retired) REMOVE_RETIRED=1 ;;
    --project-root) shift; PROJECT_ROOT="$1" ;;
    --dest) shift; DEST="$1" ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

case "$DEST" in
  # A drive-letter path is absolute under Git Bash. Without this it is treated
  # as relative and the skills land in a nested folder under the repository.
  /* | [A-Za-z]:/* | [A-Za-z]:\\*) DEST_ROOT="$DEST" ;;
  *) DEST_ROOT="$PROJECT_ROOT/$DEST" ;;
esac

mkdir_cmd() {
  if [ "$DRY_RUN" -eq 1 ]; then echo "DRY RUN mkdir -p $1"; else mkdir -p "$1"; fi
}

copy_skill() {
  src="$1"; dst="$2"
  [ -f "$src/SKILL.md" ] || { echo "invalid skill source: $src" >&2; exit 1; }
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY RUN copy $src -> $dst"
  else
    mkdir -p "$dst"
    cp -R "$src"/. "$dst"/
  fi
}

# Graph Coder's skills describe a ten-phase lifecycle this one replaced. Both
# sets installed together offer the same phases under different names, and a run
# can select either.
report_retired() {
  root="$1"
  for pair in \
    "graph-coder:graph-coder-lite" \
    "plan-forge:gcl-plan" \
    "execution-manager:gcl-review" \
    "plan-rehearsal:(removed: there is no rehearsal phase)" \
    "concept-grill:(merged into the GROUND phase)" \
    "technical-research:(merged into the PLAN phase)" \
    "delegation-graph:(the plan file is the graph)" \
    "routing-plan:(use gcl route set)"
  do
    name=${pair%%:*}; replacement=${pair#*:}
    [ -f "$root/$name/SKILL.md" ] || continue
    if [ "$REMOVE_RETIRED" -eq 1 ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "DRY RUN remove superseded skill $root/$name"
      else
        rm -rf "$root/$name"
        echo "REMOVED superseded skill $root/$name"
      fi
    else
      echo "WARNING: full Graph Coder skill still installed: $root/$name. It shadows $replacement and a run can select it instead. Keep it deliberately, or re-run with --remove-retired." >&2
    fi
  done
}

mkdir_cmd "$DEST_ROOT"
for skill in graph-coder-lite gcl-plan gcl-review; do
  copy_skill "$SOURCE_ROOT/$skill" "$DEST_ROOT/$skill"
done
report_retired "$DEST_ROOT"
echo "Graph Coder Lite skills installed idempotently. No secrets read or written."
