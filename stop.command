#!/bin/bash
# توقف داشبورد و موتور معامله
pkill -f "scripts/paper_daemon.py" 2>/dev/null
pkill -f "streamlit run app.py" 2>/dev/null
if [ -f ".caffeinate.pid" ]; then
  kill "$(cat .caffeinate.pid)" 2>/dev/null
  rm -f .caffeinate.pid
fi
echo "Stopped."
