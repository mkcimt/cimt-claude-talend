#!/usr/bin/env bash
# doctor.sh — verify cimt-claude-talend is wired up correctly.
#
# Usage:
#   ./setup/doctor.sh                  # check the env-var + repo only
#   ./setup/doctor.sh <project-dir>    # also check the project integration

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="${1:-}"

ok()   { echo "    [OK]   $*"; }
warn() { echo "    [WARN] $*"; FAIL=1; }
err()  { echo "    [FAIL] $*"; FAIL=1; }
FAIL=0

echo "==> Repo: $REPO_ROOT"

# ---- env var ----
echo "==> Env var CIMT_TALEND_PATTERNS"
if [[ -n "${CIMT_TALEND_PATTERNS:-}" ]]; then
  if [[ "$CIMT_TALEND_PATTERNS" == "$REPO_ROOT" ]]; then
    ok "set to repo root"
  else
    warn "set to '$CIMT_TALEND_PATTERNS' but this repo is at '$REPO_ROOT'"
  fi
else
  warn "not set in this shell — did you 'source' your rc after install?"
fi

# ---- expected files ----
echo "==> Expected knowledge files"
EXPECTED=(
  "knowledge/INDEX.md"
  "knowledge/mechanics/item-file-format.md"
  "knowledge/mechanics/git-workflow.md"
  "knowledge/mechanics/item-properties-touch.md"
  "knowledge/mechanics/studio-noise-filter.md"
  "knowledge/patterns/context-variables.md"
  "knowledge/tmc/task-management.md"
  "knowledge/tmc/microservice-lifecycle.md"
  "knowledge/tmc/deployment-modes.md"
  "knowledge/tmc/known-bugs.md"
  "knowledge/build-publish/release-runbook.md"
  "knowledge/build-publish/maven-build.md"
  "knowledge/code-review/principles.md"
  "knowledge/documentation/conventions.md"
)
for f in "${EXPECTED[@]}"; do
  if [[ -f "$REPO_ROOT/$f" ]]; then
    ok "$f"
  else
    err "$f MISSING"
  fi
done

# ---- skills + agents ----
echo "==> Skills"
shopt -s nullglob
for f in "$REPO_ROOT"/skills/*.md; do
  ok "$(basename "$f")"
done
echo "==> Agents"
for f in "$REPO_ROOT"/agents/*.md; do
  ok "$(basename "$f")"
done

# ---- python tools ----
echo "==> Tools"
for tool in tmc_release.py tmc_microservice_ops.py touch_item_properties.py; do
  if [[ -f "$REPO_ROOT/tools/$tool" ]]; then
    if python3 -c "import ast,sys; ast.parse(open('$REPO_ROOT/tools/$tool').read())" 2>/dev/null; then
      ok "$tool (syntactically valid)"
    else
      err "$tool fails to parse"
    fi
  else
    err "$tool MISSING"
  fi
done

# ---- project integration ----
if [[ -n "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
  echo "==> Project: $PROJECT_DIR"
  CLAUDE_DIR="$PROJECT_DIR/.claude"

  if [[ -d "$CLAUDE_DIR/commands" ]]; then
    ok ".claude/commands/ exists"
    linked=0
    for l in "$CLAUDE_DIR/commands"/*; do
      [[ -L "$l" ]] && linked=$((linked+1))
    done
    ok "$linked symlinked command(s)"
  else
    warn ".claude/commands/ missing — run install.sh"
  fi

  if [[ -d "$CLAUDE_DIR/agents" ]]; then
    ok ".claude/agents/ exists"
  else
    warn ".claude/agents/ missing — run install.sh"
  fi

  if [[ -f "$PROJECT_DIR/CLAUDE.md" ]]; then
    if grep -q "CIMT_TALEND_PATTERNS" "$PROJECT_DIR/CLAUDE.md"; then
      ok "CLAUDE.md references CIMT_TALEND_PATTERNS"
    else
      warn "CLAUDE.md does not reference CIMT_TALEND_PATTERNS — merge in the template sections"
    fi
  else
    warn "CLAUDE.md missing — run install.sh"
  fi

  if [[ -f "$CLAUDE_DIR/talend.config.json" ]]; then
    ok ".claude/talend.config.json exists"
  else
    warn ".claude/talend.config.json missing"
  fi
fi

echo
if [[ $FAIL -eq 0 ]]; then
  echo "==> All checks passed."
  exit 0
else
  echo "==> Some checks failed — see above."
  exit 1
fi
