#!/usr/bin/env bash
# Build the LMS submission zip: source + docs + sample data, without the
# virtualenv, caches or locally indexed data.
#
# The .env file (with the API key) IS included so graders can run the app
# without their own key. Pass --no-env to leave it out (e.g. for sharing publicly).
set -euo pipefail

include_env=1
[ "${1:-}" = "--no-env" ] && include_env=0

cd "$(dirname "$0")/.."
name="$(basename "$PWD")"
out="dist/${name}-$(date +%Y%m%d).zip"
mkdir -p dist
rm -f "$out"

cd ..
zip -rq "$name/$out" "$name" \
  -x "$name/.venv/*" \
  -x "$name/.cache/*" \
  -x "$name/dist/*" \
  -x "$name/.git/*" \
  -x "$name/data/qdrant/*" \
  -x "$name/data/tables.duckdb*" \
  -x "$name/data/app.db*" \
  -x "$name/logs/*" \
  -x "$name/data/eval/results/*" \
  -x "$name/data/uploads/*" \
  -x "*/__pycache__/*" \
  -x "*/.pytest_cache/*" \
  -x "*.DS_Store"

if [ "$include_env" = 0 ]; then
  zip -dq "$name/$out" "$name/.env" 2>/dev/null || true
  echo "NOTE: .env excluded (--no-env)."
elif unzip -l "$name/$out" | grep -q "$name/.env$"; then
  echo "WARNING: .env (API key) is inside the zip - share it only with the LMS/graders."
else
  echo "NOTE: no .env file found; the zip has no API key."
fi
echo "Created $name/$out"
unzip -l "$name/$out" | tail -1
