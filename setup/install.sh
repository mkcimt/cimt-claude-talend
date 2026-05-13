#!/usr/bin/env bash
# install.sh — set up cimt-claude-talend in a Talend project.
#
# Usage:
#   ./setup/install.sh <absolute-path-to-talend-project>
#   ./setup/install.sh --uninstall <absolute-path-to-talend-project>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat >&2 <<USAGE
Usage: $0 [options] <absolute-path-to-talend-project>

Options:
  --uninstall   Remove symlinks from <project>/.claude/, leave files alone.
  -h, --help    Show this help.

The installer is idempotent and safe to run on multiple Talend projects.
Each invocation creates / refreshes the symlinks in that project's .claude/
and never overwrites an existing CLAUDE.md or talend.config.json.
USAGE
  exit 2
}

UNINSTALL=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --uninstall)  UNINSTALL=1 ;;
    -h|--help)    usage ;;
    *)            ARGS+=("$a") ;;
  esac
done
set -- "${ARGS[@]:-}"

PROJECT_DIR="${1:-}"
[[ -z "$PROJECT_DIR" ]] && usage
[[ ! -d "$PROJECT_DIR" ]] && { echo "Not a directory: $PROJECT_DIR" >&2; exit 1; }

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
CLAUDE_DIR="$PROJECT_DIR/.claude"

echo "==> cimt-claude-talend"
echo "    repo:    $REPO_ROOT"
echo "    project: $PROJECT_DIR"
echo

if [[ $UNINSTALL -eq 1 ]]; then
  echo "==> Removing symlinks under $CLAUDE_DIR"
  for d in commands agents; do
    target="$CLAUDE_DIR/$d"
    if [[ -L "$target" ]]; then
      rm "$target"
      echo "    removed symlink: $target"
    elif [[ -d "$target" ]]; then
      # Remove only files that are symlinks pointing into our repo.
      find "$target" -maxdepth 1 -type l | while read -r link; do
        if readlink "$link" | grep -q "$REPO_ROOT"; then
          rm "$link"
          echo "    removed symlink: $link"
        fi
      done
    fi
  done
  echo
  echo "Done. Your CLAUDE.md and talend.config.json are untouched."
  echo "Remove the CIMT_TALEND_PATTERNS line from your shell rc manually if no projects use it."
  exit 0
fi

# ---- install path ----

# 1. Record CIMT_TALEND_PATTERNS in shell rc.
SHELL_RC=""
case "${SHELL:-}" in
  */zsh)  SHELL_RC="$HOME/.zshrc" ;;
  */bash) SHELL_RC="$HOME/.bashrc" ;;
  *)      SHELL_RC="$HOME/.profile" ;;
esac

LINE="export CIMT_TALEND_PATTERNS=\"$REPO_ROOT\""
if [[ -f "$SHELL_RC" ]] && grep -q "^export CIMT_TALEND_PATTERNS=" "$SHELL_RC"; then
  # Update existing line.
  sed -i.bak "s|^export CIMT_TALEND_PATTERNS=.*|$LINE|" "$SHELL_RC"
  echo "==> Updated CIMT_TALEND_PATTERNS in $SHELL_RC"
else
  echo "$LINE" >> "$SHELL_RC"
  echo "==> Added CIMT_TALEND_PATTERNS to $SHELL_RC"
fi
echo "    -> $REPO_ROOT"
echo "    (open a new shell or 'source $SHELL_RC' to pick it up)"
echo

# 2. Create .claude structure and symlinks.
mkdir -p "$CLAUDE_DIR/commands" "$CLAUDE_DIR/agents"

echo "==> Linking skills into $CLAUDE_DIR/commands"
for f in "$REPO_ROOT"/skills/*.md; do
  [[ -e "$f" ]] || continue
  name="$(basename "$f")"
  target="$CLAUDE_DIR/commands/$name"
  if [[ -L "$target" || -e "$target" ]]; then
    rm "$target"
  fi
  ln -s "$f" "$target"
  echo "    $name -> $f"
done
echo

echo "==> Linking agents into $CLAUDE_DIR/agents"
for f in "$REPO_ROOT"/agents/*.md; do
  [[ -e "$f" ]] || continue
  name="$(basename "$f")"
  target="$CLAUDE_DIR/agents/$name"
  if [[ -L "$target" || -e "$target" ]]; then
    rm "$target"
  fi
  ln -s "$f" "$target"
  echo "    $name -> $f"
done
echo

# 3. CLAUDE.md handling.
if [[ ! -f "$PROJECT_DIR/CLAUDE.md" ]]; then
  cp "$REPO_ROOT/templates/CLAUDE.md.template" "$PROJECT_DIR/CLAUDE.md"
  echo "==> Wrote $PROJECT_DIR/CLAUDE.md from template."
  echo "    The fixed integration block is copy-paste — nothing to fill in."
  echo "    Add your own project sections (description, repo layout, git rules, user profile) above or below the block."
else
  echo "==> $PROJECT_DIR/CLAUDE.md exists; not overwriting."
  echo "    Make sure it contains the cimt-claude-talend integration block —"
  echo "    see $REPO_ROOT/templates/CLAUDE.md.template for the canonical version."
fi
echo

# 4. talend.config.json scaffold.
if [[ ! -f "$CLAUDE_DIR/talend.config.json" ]]; then
  cp "$REPO_ROOT/templates/talend.config.json.example" "$CLAUDE_DIR/talend.config.json"
  echo "==> Wrote $CLAUDE_DIR/talend.config.json from example — fill in real values."
else
  echo "==> $CLAUDE_DIR/talend.config.json exists; not overwriting."
fi
echo

# 5. .gitignore — make sure the developer-specific symlinks aren't tracked.
GITIGNORE="$PROJECT_DIR/.gitignore"
GITIGNORE_ENTRIES=(
  ".claude/commands/"
  ".claude/agents/"
  ".claude/settings.local.json"
)
GITIGNORE_HEADER="# cimt-claude-talend — developer-specific Claude Code state (do not commit)"

if [[ ! -f "$GITIGNORE" ]]; then
  {
    echo "$GITIGNORE_HEADER"
    printf '%s\n' "${GITIGNORE_ENTRIES[@]}"
  } > "$GITIGNORE"
  echo "==> Created $GITIGNORE with cimt-claude-talend entries."
else
  added=0
  for entry in "${GITIGNORE_ENTRIES[@]}"; do
    # Match the entry whether it's plain or has a leading slash, ignoring inline comments.
    if ! grep -qxE "^/?${entry//./\\.}\$" "$GITIGNORE"; then
      if [[ $added -eq 0 ]]; then
        # Add a blank line and header on first addition.
        printf '\n%s\n' "$GITIGNORE_HEADER" >> "$GITIGNORE"
      fi
      echo "$entry" >> "$GITIGNORE"
      added=$((added+1))
    fi
  done
  if [[ $added -gt 0 ]]; then
    echo "==> Added $added entry(ies) to $GITIGNORE."
  else
    echo "==> $GITIGNORE already covers the cimt-claude-talend entries."
  fi
fi

# Untrack any commands/agents symlinks that are currently in the index
# (typical when a project tracked these files before adopting cimt-claude-talend).
if git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  to_untrack="$(git -C "$PROJECT_DIR" ls-files .claude/commands/ .claude/agents/ 2>/dev/null || true)"
  if [[ -n "$to_untrack" ]]; then
    echo "==> Untracking pre-existing .claude/commands/ and .claude/agents/ files in git index:"
    echo "$to_untrack" | sed 's/^/    /'
    echo "$to_untrack" | xargs git -C "$PROJECT_DIR" rm --cached -q
    echo "    -> commit the resulting changes (and the updated .gitignore) on a feature branch."
  fi
fi
echo

echo "==> Done. Run setup/doctor.sh to verify."
