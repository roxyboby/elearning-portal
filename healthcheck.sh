#!/usr/bin/env bash
URL="http://192.168.1.216:8000/healthz"
if curl -fsS "$URL" >/dev/null; then
  echo "[$(date)] OK"
else
  echo "[$(date)] DOWN"
fi
