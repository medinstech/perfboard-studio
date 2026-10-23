#!/usr/bin/env bash
# Fail unless a built bundle carries every package mesh, and the licence they travel under.
#
#   bash packaging/check-bundle-models.sh ./dist                     # Windows, Linux
#   bash packaging/check-bundle-models.sh ./dist/PerfboardStudio.app # macOS
#
# Run from the repository root, after `pyinstaller perfboard-studio.spec`. The meshes are
# DATA, not modules, so no import fails without them and no window looks broken: the 3D
# view quietly draws the generated body for every part instead. That is how every
# installer from 0.12.0 to 0.21.0 shipped -- release.yml checked the wheel for them and
# never the bundles. File for file against the source, so a mesh added later and missed
# by the spec is caught too, and the LICENSE and NOTICE.md are part of that list: CC-BY-SA
# lets the meshes be redistributed only with them.
set -euo pipefail

bundle=${1:?usage: check-bundle-models.sh <bundle directory>}
source_dir=src/perfboard_studio/ui/models

# Wherever the bundle put it: `_internal/` on Windows and Linux, `Contents/Resources/` in
# a macOS .app. A real directory, so a symlink to it elsewhere in the .app is not counted.
packed=$(find "$bundle" -type d -path '*/perfboard_studio/ui/models' | head -n 1)
if [ -z "$packed" ]; then
  echo "::error::$bundle has no perfboard_studio/ui/models -- the 3D view would draw no borrowed package"
  exit 1
fi

missing=0
count=0
for source in "$source_dir"/*; do
  name=$(basename "$source")
  count=$((count + 1))
  if ! cmp -s "$source" "$packed/$name"; then
    echo "::error::$packed/$name is missing or differs from $source"
    missing=$((missing + 1))
  fi
done

if [ "$missing" -ne 0 ]; then
  exit 1
fi
echo "$packed: all $count files of $source_dir, LICENSE and NOTICE.md included"
