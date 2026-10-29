#!/usr/bin/env bash
# Build the LMS submission zip: source + docs + sample data + the .env file
# (so graders can run the app with the project's API key), without the
# virtualenv, caches, logs or locally indexed data.
# Pass --no-env to leave .env out (for sharing outside the LMS).
# The key in .env should be revoked once grading is confirmed.
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
  echo "NOTE: .env excluded (--no-env); the recipient must create their own .env."
elif unzip -l "$name/$out" | grep -q "$name/.env$"; then
  echo "NOTE: .env (with the API key) is inside the zip. Share it only through the LMS and revoke the key after grading."
else
  echo "NOTE: no .env file exists; the zip has no API key."
fi
echo "Created $name/$out"
unzip -l "$name/$out" | tail -1
