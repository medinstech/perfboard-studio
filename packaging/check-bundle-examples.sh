#!/usr/bin/env bash
# Fail unless a built bundle carries every example the application offers.
#
#   bash packaging/check-bundle-examples.sh ./dist                     # Windows, Linux
#   bash packaging/check-bundle-examples.sh ./dist/PerfboardStudio.app # macOS
#
# Run from the repository root, after `pyinstaller perfboard-studio.spec`. The examples are
# DATA, so no import fails without one and Home simply offers what it finds: the project
# folder `examples/ne555-blinker` -- Home's first door and the tour's board -- was missing
# from every installer until 0.24, because the spec listed `examples/` one level deep.
# File for file against what git tracks, filtered as the spec filters it, so an example
# added later in a folder of its own is caught too.
set -euo pipefail

bundle=${1:?usage: check-bundle-examples.sh <bundle directory>}

# Wherever the bundle put them: `_internal/` on Windows and Linux, `Contents/Resources/` in
# a macOS .app. Found by a file only the examples have, since other packages carry folders
# called `examples` of their own.
marker=$(find "$bundle" -type f -path '*/examples/ne555-astable.perf' | head -n 1)
if [ -z "$marker" ]; then
  echo "::error::$bundle has no examples/ne555-astable.perf -- Home would offer no examples"
  exit 1
fi
packed=$(dirname "$marker")

missing=0
count=0
while IFS= read -r source; do
  case "$source" in
    */outputs/*) continue ;;
    *.perf|*.net|*/README.md|README.md) ;;
    *) continue ;;
  esac
  count=$((count + 1))
  relative=${source#examples/}
  if ! cmp -s "$source" "$packed/$relative"; then
    echo "::error::$packed/$relative is missing or differs from $source"
    missing=$((missing + 1))
  fi
done < <(git ls-files examples)

if [ "$count" -eq 0 ]; then
  echo "::error::git tracks no examples here -- run this from the repository root"
  exit 1
fi
if [ "$missing" -ne 0 ]; then
  exit 1
fi
echo "$packed: all $count example files, the project folders included"
