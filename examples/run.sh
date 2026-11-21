#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
status=0
drawing-handoff-check examples/sheet-list.csv examples/drawings \
    --project "Sample Bayside Pavilion" \
    --rules examples/filename-rules.json \
    --output-dir examples/output "$@" || status=$?
# The fixture deliberately has findings, which the CLI signals with status 1.
case "$status" in
    0|1) exit 0 ;;
    *) exit "$status" ;;
esac
