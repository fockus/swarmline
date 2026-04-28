#!/bin/bash
# Sync stable main to public repo (github.com/fockus/swarmline)
#
# Usage: ./scripts/sync-public.sh [--tags] [--dry-run]
#
# Prerequisites:
#   - On main branch
#   - Working tree clean
#   - All tests passing
#
# What it does:
#   1. Verifies main is clean and tested
#   2. Creates a temporary branch without private files
#   3. Pushes filtered branch as main to public remote
#   4. Cleans up temporary branch
#   5. Optionally pushes tags (--tags)
#
# Private files/dirs (excluded from public — see PRIVATE_PATHS array below):
#   - .memory-bank/        (project memory, plans, notes, reports)
#   - .specs/              (internal spec drafts)
#   - .planning/           (GSD planning artifacts)
#   - .factory/            (factory pipeline configs)
#   - .pipeline.yaml       (private build pipeline)
#   - CLAUDE.md            (Claude Code instructions)
#   - RULES.md             (development rules)
#   - AGENTS.md            (replaced with AGENTS.public.md)
#   - AGENTS.public.md     (source for public AGENTS.md)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
PUSH_TAGS=false

for arg in "$@"; do
    case "$arg" in
        --tags) PUSH_TAGS=true ;;
        --dry-run) DRY_RUN=true ;;
    esac
done

# Private files/dirs to exclude from public repo
PRIVATE_PATHS=(
    ".memory-bank"
    "CLAUDE.md"
    "RULES.md"
    "AGENTS.md"
    "AGENTS.public.md"
    ".specs"
    ".planning"
    ".factory"
    ".pipeline.yaml"
)

TEMP_BRANCH="_sync_public_temp"

cleanup() {
    # Return to main and delete temp branch
    git checkout main --quiet 2>/dev/null || true
    git branch -D "$TEMP_BRANCH" --quiet 2>/dev/null || true
}
trap cleanup EXIT

# Check branch
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then
    echo -e "${RED}Error: Must be on main branch (currently on '$BRANCH')${NC}"
    exit 1
fi

# Check clean working tree
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}Error: Working tree not clean. Commit or stash changes first.${NC}"
    git status --short
    exit 1
fi

# Check public remote exists
PUBLIC_REMOTE="${SWARMLINE_PUBLIC_REMOTE:-public}"
if ! git remote get-url "$PUBLIC_REMOTE" &>/dev/null; then
    echo -e "${RED}Error: '$PUBLIC_REMOTE' remote not configured.${NC}"
    echo "Run: git remote add $PUBLIC_REMOTE https://github.com/fockus/swarmline.git"
    exit 1
fi

# Run tests
echo -e "${YELLOW}Running tests...${NC}"
if ! pytest -q 2>&1 | tail -3; then
    echo -e "${RED}Error: Tests failed. Fix before syncing to public.${NC}"
    exit 1
fi

# Create temporary branch from main
echo -e "${YELLOW}Creating filtered branch (excluding private files)...${NC}"
git checkout -b "$TEMP_BRANCH" --quiet

# Remove private files from the temporary branch index
REMOVED=()
for path in "${PRIVATE_PATHS[@]}"; do
    if git ls-files --error-unmatch "$path" &>/dev/null; then
        git rm -r --cached --quiet "$path"
        REMOVED+=("$path")
    fi
done

if [ ${#REMOVED[@]} -gt 0 ]; then
    echo -e "  Excluded: ${REMOVED[*]}"
fi

# Replace AGENTS.md with public-safe version
if [ -f "AGENTS.public.md" ]; then
    cp AGENTS.public.md AGENTS.md
    git add AGENTS.md
    echo -e "  Replaced: AGENTS.md with public-safe version"
fi

if [ -n "$(git status --porcelain)" ]; then
    git commit --quiet -m "sync: prepare public-safe snapshot"
else
    echo -e "  No private files to exclude"
fi

# Push to public
if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[DRY RUN] Would push to public...${NC}"
    echo "  git push public ${TEMP_BRANCH}:main --force"
else
    echo -e "${YELLOW}Pushing to public (filtered main)...${NC}"
    git push "$PUBLIC_REMOTE" "${TEMP_BRANCH}:main" --force
fi

# Push tags if requested
if [ "$PUSH_TAGS" = true ]; then
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY RUN] Would push tags to public...${NC}"
    else
        echo -e "${YELLOW}Pushing tags to public...${NC}"
        git push "$PUBLIC_REMOTE" --tags
    fi
fi

# Cleanup happens via trap

echo -e "${GREEN}Synced to public repo.${NC}"
echo "  Public:   $(git remote get-url "$PUBLIC_REMOTE")"
echo "  Branch:   main"
echo "  Commit:   $(git log --oneline -1 main)"
echo "  Excluded: ${REMOVED[*]:-none}"
