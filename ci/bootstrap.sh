#!/usr/bin/env bash
# เตรียมสองโคลนของ repo ข้อมูล: สายข้อมูลอยู่บน main ส่วนไฟล์สถานะอยู่บนกิ่งของตัวเอง
#
# ที่แยกกิ่งเพราะไฟล์สถานะเป็นก้อนบีบอัดที่ถูกเขียนทับทั้งไฟล์ทุกครั้ง ถ้าปนอยู่บน main
# ประวัติของสายข้อมูลจะถูกก้อนใหม่ทับถมจนอ่านส่วนต่างไม่ได้ ทั้งที่สายข้อมูลเป็นไฟล์ต่อท้าย
# ที่ git หาส่วนต่างได้สวย ๆ อยู่แล้ว
set -euo pipefail

# runner.temp ใช้ในบล็อก env ระดับ job ไม่ได้ จึงตั้งที่นี่แล้วส่งต่อให้ขั้นตอนถัดไป
DATA="${DATA:-$RUNNER_TEMP/data}"
STATE="${STATE:-$RUNNER_TEMP/state}"
{ echo "DATA=$DATA"; echo "STATE=$STATE"; } >> "$GITHUB_ENV"

REMOTE="https://x-access-token:${GH_TOKEN}@github.com/${DATA_REPO}.git"

git config --global user.name  "freelance-market collector"
git config --global user.email "collector@users.noreply.github.com"

# --- สายข้อมูลบน main ---
if git clone --depth 1 "$REMOTE" "$DATA" 2>/dev/null && [ -n "$(git -C "$DATA" rev-parse --quiet --verify HEAD 2>/dev/null || true)" ]; then
  echo "โคลน main ของ repo ข้อมูลแล้ว"
else
  echo "repo ข้อมูลยังว่าง — เริ่ม main ใหม่"
  rm -rf "$DATA"; mkdir -p "$DATA"
  git -C "$DATA" init -q -b main
  git -C "$DATA" remote add origin "$REMOTE"
fi
# ไฟล์สถานะอยู่คนละกิ่ง ตัวไล่ push ของ main ต้องไม่แตะมัน
printf 'state.json.gz\nstate.json.gz.tmp\n' > "$DATA/.gitignore"

# --- ไฟล์สถานะบนกิ่ง state ---
if git clone --depth 1 --branch state "$REMOTE" "$STATE" 2>/dev/null; then
  echo "โคลนกิ่ง state แล้ว"
  # ที่เก็บมีสถานะอยู่ ต้องเอากลับเข้าที่ก่อนตัวเก็บเริ่ม ไม่งั้นมันจะเห็นว่าสถานะหาย
  [ -f "$STATE/state.json.gz" ] && cp "$STATE/state.json.gz" "$DATA/state.json.gz"
else
  echo "ยังไม่มีกิ่ง state — สร้างใหม่"
  rm -rf "$STATE"; mkdir -p "$STATE"
  git -C "$STATE" init -q -b state
  git -C "$STATE" remote add origin "$REMOTE"
fi

ls -la "$DATA"
