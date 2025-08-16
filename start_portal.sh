#!/bin/bash
cd ~/e_learning_portal || exit 1
source venv/bin/activate
# Start Gunicorn in background
gunicorn -w 2 -k gthread --threads 4 --bind 192.168.1.216:8000 app:app &
# Wait briefly to ensure Gunicorn is ready
sleep 3
# Start Cloudflare Tunnel in foreground
cloudflared tunnel --config ~/.cloudflared/config.yml run elearning-pi
