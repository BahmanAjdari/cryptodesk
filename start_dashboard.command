#!/bin/bash
# اجرای داشبورد + موتور معامله پس‌زمینه با دابل‌کلیک — بدون نیاز به ترمینال
# ترمینال را می‌توانی بعد از اجرا ببندی؛ هر دو در پس‌زمینه می‌مانند.
cd "$(dirname "$0")"
pip3 install -q -r requirements.txt
# جلوگیری از اجرای تکراری
pkill -f "scripts/paper_daemon.py" 2>/dev/null
pkill -f "streamlit run app.py" 2>/dev/null
sleep 1
nohup python3 scripts/paper_daemon.py > paper_daemon.log 2>&1 &
# جلوگیری از Hibernate/Sleep مک تا وقتی بات روشن است (فقط macOS)
if command -v caffeinate >/dev/null 2>&1; then
  nohup caffeinate -i -s >/dev/null 2>&1 &
  echo $! > .caffeinate.pid
fi
# headless=true تا خود استریم‌لیت مرورگر باز نکند؛ فقط دستور open پایین یک بار باز می‌کند
nohup streamlit run app.py --server.headless true > streamlit.log 2>&1 &
sleep 4
open "http://localhost:8501" 2>/dev/null || xdg-open "http://localhost:8501" 2>/dev/null || true
echo "Dashboard: http://localhost:8501"
