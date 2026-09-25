#!/usr/bin/env bash
# ปิดท้าย job: ดันสายข้อมูลที่เหลือขึ้น main แล้ว commit ไฟล์สถานะลงกิ่ง state
#
# สถานะถูก commit ตอนนี้ที่เดียว เพราะมันคือ "เรารู้อะไรอยู่ตอนนี้" ไม่ใช่ข้อมูลที่เก็บได้
# ถ้า push ไม่ผ่าน ต้องจบด้วยรหัสผิดพลาดให้ job แดง — โทเคนหมดอายุถูกจับตรงนี้
set -euo pipefail

# ลองซ้ำก่อนยอมแพ้ เพราะ GitHub ตอบพังชั่วคราวได้จริง (500 และปฏิเสธกุญแจที่ใช้ได้ห่างกันไม่ถึง
# สองนาทีเมื่อ 2026-09-24) และตรงนี้คือโอกาสสุดท้าย — runner หายไปพร้อมทุกอย่างที่ยังไม่ขึ้น
# รวมเวลารอ 90 วินาที อยู่ในขอบ 10 นาทีระหว่างตัวเก็บออกเองกับเพดาน job
push() {
  local i
  for i in 1 2 3; do
    git -C "$1" push origin "$2" && return 0
    [ "$i" = 3 ] || { echo "push $2 ไม่ผ่าน ลองใหม่ใน $((i * 30)) วินาที"; sleep $((i * 30)); }
  done
  return 1
}

# หยุดตัวไล่ push ก่อน ไม่งั้นสองตัวจะ commit บนโคลนเดียวกันพร้อมกัน
pkill -f push_loop.sh 2>/dev/null || true
sleep 1

git -C "$DATA" add -A
if ! git -C "$DATA" diff --cached --quiet; then
  git -C "$DATA" commit -qm "data $(date -u '+%Y-%m-%d %H:%M') UTC (ปิดท้าย)"
fi
# push เสมอแม้ไม่มีอะไรใหม่ให้ commit — commit ของตัวไล่ push ที่ push ไม่ผ่านยังค้างอยู่ในโคลน
# และนี่คือโอกาสสุดท้ายที่จะพามันขึ้นไป ถ้าไม่มีอะไรค้าง git ตอบว่าตรงกันอยู่แล้วและไม่ทำอะไร
if git -C "$DATA" rev-parse -q --verify HEAD >/dev/null; then
  push "$DATA" main
  # ขั้นตรวจถัดไปใช้แฟ้มนี้แยกว่า push ระหว่างทางที่เคยล้ม ถูกตามเก็บครบแล้วหรือยัง
  touch "$RUNNER_TEMP/final-push-ok"
  echo "ดันสายข้อมูลรอบสุดท้ายแล้ว"
else
  echo "ยังไม่มีสายข้อมูลเลย"
fi

if [ -f "$DATA/state.json.gz" ]; then
  cp "$DATA/state.json.gz" "$STATE/state.json.gz"
  git -C "$STATE" add state.json.gz
  if ! git -C "$STATE" diff --cached --quiet; then
    git -C "$STATE" commit -qm "state $(date -u '+%Y-%m-%d %H:%M') UTC"
    push "$STATE" state
    echo "commit สถานะลงกิ่ง state แล้ว"
  else
    echo "สถานะไม่เปลี่ยนจากรอบก่อน"
  fi
else
  echo "::warning::ไม่พบไฟล์สถานะ — ตัวเก็บน่าจะไม่ได้เริ่มเลย"
fi
