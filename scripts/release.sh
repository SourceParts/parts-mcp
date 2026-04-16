#!/usr/bin/env bash
# Usage: ./scripts/release.sh patch|minor|major [--prerelease rc1]
#
# Bumps version in all files, commits, tags, and pushes.
# The tag push triggers CI which handles PyPI + MCP Registry publishing.

set -euo pipefail

BUMP="${1:-}"
PRERELEASE=""

shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prerelease) PRERELEASE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$BUMP" ]] || [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
  echo "Usage: ./scripts/release.sh patch|minor|major [--prerelease rc1]"
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

# Read current version from pyproject.toml
CURRENT=$(python3 -c "
import re
with open('pyproject.toml') as f:
    m = re.search(r'version\s*=\s*\"(.+?)\"', f.read())
    print(m.group(1))
")

# Strip any existing prerelease suffix for arithmetic
BASE="${CURRENT%%-*}"
IFS='.' read -r MAJOR MINOR PATCH <<< "$BASE"

case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

VERSION="${MAJOR}.${MINOR}.${PATCH}"
if [[ -n "$PRERELEASE" ]]; then
  VERSION="${VERSION}-${PRERELEASE}"
fi

echo "Bumping: ${CURRENT} -> ${VERSION}"
echo ""

# Update pyproject.toml
python3 -c "
import re
with open('pyproject.toml') as f:
    content = f.read()
content = re.sub(r'(version\s*=\s*\").+?(\")', r'\g<1>${VERSION}\2', content, count=1)
with open('pyproject.toml', 'w') as f:
    f.write(content)
"

# Update __init__.py
python3 -c "
import re
with open('parts_mcp/__init__.py') as f:
    content = f.read()
content = re.sub(r'__version__\s*=\s*\".+?\"', '__version__ = \"${VERSION}\"', content)
with open('parts_mcp/__init__.py', 'w') as f:
    f.write(content)
"

# Update package.json
python3 -c "
import json
with open('package.json') as f:
    data = json.load(f)
data['version'] = '${VERSION}'
with open('package.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"

# Update server.json
python3 -c "
import json
with open('server.json') as f:
    data = json.load(f)
data['version'] = '${VERSION}'
for pkg in data.get('packages', []):
    pkg['version'] = '${VERSION}'
with open('server.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"

# Verify all match
PYPROJECT=$(python3 -c "import re; print(re.search(r'version\s*=\s*\"(.+?)\"', open('pyproject.toml').read()).group(1))")
INIT=$(python3 -c "import re; print(re.search(r'__version__\s*=\s*\"(.+?)\"', open('parts_mcp/__init__.py').read()).group(1))")
PKG=$(python3 -c "import json; print(json.load(open('package.json'))['version'])")
SRV=$(python3 -c "import json; print(json.load(open('server.json'))['version'])")

echo "  pyproject.toml: ${PYPROJECT}"
echo "  __init__.py:    ${INIT}"
echo "  package.json:   ${PKG}"
echo "  server.json:    ${SRV}"

if [[ "$PYPROJECT" != "$VERSION" ]] || [[ "$INIT" != "$VERSION" ]] || [[ "$PKG" != "$VERSION" ]] || [[ "$SRV" != "$VERSION" ]]; then
  echo "ERROR: Version mismatch!"
  exit 1
fi

echo ""
echo "All versions updated to ${VERSION}"

# Commit, tag, push
git add pyproject.toml parts_mcp/__init__.py package.json server.json
git commit -m "chore: bump version to ${VERSION}"
git tag "v${VERSION}"
git push origin main
git push origin "v${VERSION}"

echo ""
echo "Pushed v${VERSION} -- CI will publish to PyPI + MCP Registry"
