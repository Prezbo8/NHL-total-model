#!/bin/zsh
# Daily: settle yesterday's paper trades, then project + log today's games.
cd "$HOME/nhl-totals-model" || exit 1
PY="$HOME/venv_mlb/bin/python3"
{
  echo "===== $(date '+%Y-%m-%d %H:%M') ====="
  "$PY" paper.py settle
  "$PY" model.py today 2>&1 | tr '\r' '\n' | grep -v '^  goalie [0-9]'
  "$PY" paper.py report
  # push the updated paper-trade record (and refreshed data files) to GitHub
  GIT=/opt/homebrew/bin/git
  "$GIT" add -u
  if ! "$GIT" diff --cached --quiet; then
    "$GIT" commit -q -m "daily update $(date '+%Y-%m-%d %H:%M')" && "$GIT" push -q && echo "pushed to GitHub"
  else
    echo "no changes to push"
  fi
} >> daily.log 2>&1
