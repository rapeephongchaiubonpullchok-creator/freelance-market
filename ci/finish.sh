#!/usr/bin/env bash
# ปิดท้าย job: ดันสายข้อมูลที่เหลือขึ้น main แล้ว commit ไฟล์สถานะลงกิ่ง state
#
# สถานะถูก commit ตอนนี้ที่เดียว เพราะมันคือ "เรารู้อะไรอยู่ตอนนี้" ไม่ใช่ข้อมูลที่เก็บได้
# ถ้า push ไม่ผ่าน ต้องจบด้วยรหัสผิดพลาดให้ job แดง — โทเคนหมดอายุถูกจับตรงนี้
set -euo pipefail

# หยุดตัวไล่ push ก่อน ไม่งั้นสองตัวจะ commit บนโคลนเดียวกันพร้อมกัน
pkill -f push_loop.sh 2>/dev/null || true
sleep 1

git -C "$DATA" add -A
if ! git -C "$DATA" diff --cached --quiet; then
  git -C "$DATA" commit -qm "data $(date -u '+%Y-%m-%d %H:%M') UTC (ปิดท้าย)"
  git -C "$DATA" push origin main
  echo "ดันสายข้อมูลรอบสุดท้ายแล้ว"
else
  echo "ไม่มีสายข้อมูลใหม่ค้างอยู่"
fi

if [ -f "$DATA/state.json.gz" ]; then
  cp "$DATA/state.json.gz" "$STATE/state.json.gz"
  git -C "$STATE" add state.json.gz
  if ! git -C "$STATE" diff --cached --quiet; then
    git -C "$STATE" commit -qm "state $(date -u '+%Y-%m-%d %H:%M') UTC"
    git -C "$STATE" push origin state
    echo "commit สถานะลงกิ่ง state แล้ว"
  else
    echo "สถานะไม่เปลี่ยนจากรอบก่อน"
  fi
else
  echo "::warning::ไม่พบไฟล์สถานะ — ตัวเก็บน่าจะไม่ได้เริ่มเลย"
fi
