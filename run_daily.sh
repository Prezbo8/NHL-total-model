#!/bin/zsh
# Daily: settle yesterday's paper trades, then project + log today's games.
cd "$HOME/nhl-totals-model" || exit 1
PY="$HOME/venv_mlb/bin/python3"
{
  echo "===== $(date '+%Y-%m-%d %H:%M') ====="
  "$PY" paper.py settle
  "$PY" model.py today 2>&1 | tr '\r' '\n' | grep -v '^  goalie [0-9]'
  "$PY" paper.py report
} >> daily.log 2>&1
