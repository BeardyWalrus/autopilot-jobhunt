#!/bin/sh
# Seed the data volume on first run, then launch the web UI.
set -e

HOME_DIR="${AUTOPILOT_HOME:-/data}"
mkdir -p "$HOME_DIR"
cd "$HOME_DIR"

if [ ! -f companies.json ]; then
  echo "First run — seeding project files into $HOME_DIR ..."
  autopilot init || true
fi

exec autopilot web
