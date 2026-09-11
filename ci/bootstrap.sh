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

# โทเคนเป็นชื่อผู้ใช้ ไม่ใช่รหัสผ่าน — เป็นรูปแบบที่ใช้ได้ทั้งโทเคนแบบเก่าและแบบละเอียด
REMOTE="https://${GH_TOKEN}@github.com/${DATA_REPO}.git"

# ตรวจโทเคนก่อนแตะ git เลย ไม่งั้นการโคลนที่พังเพราะสิทธิ์จะหน้าตาเหมือน repo ว่างเปล่า
# แล้วตัวเก็บจะเดินไปทั้ง job ก่อนจะรู้ตอนจบว่า push ไม่ได้มาตั้งแต่แรก
CODE=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${DATA_REPO}")
case "$CODE" in
  200) echo "โทเคนเข้าถึง ${DATA_REPO} ได้" ;;
  401) echo "::error::โทเคนใช้ไม่ได้ (401) — ค่าใน FM_DATA_TOKEN ผิดหรือหมดอายุแล้ว"; exit 1 ;;
  403) echo "::error::โทเคนถูกปฏิเสธ (403) — น่าจะยังไม่ได้ให้สิทธิ์ Contents ระดับอ่านเขียน"; exit 1 ;;
  404) echo "::error::โทเคนมองไม่เห็น ${DATA_REPO} (404) — น่าจะไม่ได้เลือก repo นี้ตอนออกโทเคน"; exit 1 ;;
  *)   echo "::error::ถามสิทธิ์ของโทเคนไม่สำเร็จ (HTTP ${CODE})"; exit 1 ;;
esac

git config --global user.name  "freelance-market collector"
git config --global user.email "collector@users.noreply.github.com"

# --- สายข้อมูลบน main ---
# ถึงตรงนี้แล้วโทเคนใช้ได้แน่ การโคลนที่ไม่ได้ HEAD จึงแปลว่า repo ว่างจริง ๆ ไม่ใช่เรื่องสิทธิ์
git clone --depth 1 "$REMOTE" "$DATA"
if [ -z "$(git -C "$DATA" rev-parse --quiet --verify HEAD 2>/dev/null || true)" ]; then
  echo "repo ข้อมูลยังว่าง — เริ่ม main ใหม่"
  git -C "$DATA" checkout -q -b main 2>/dev/null || true
fi
# ไฟล์สถานะอยู่คนละกิ่ง ตัวไล่ push ของ main ต้องไม่แตะมัน
printf 'state.json.gz\nstate.json.gz.tmp\n' > "$DATA/.gitignore"

# --- ไฟล์สถานะบนกิ่ง state ---
if git clone --depth 1 --branch state "$REMOTE" "$STATE" 2>&1 | tee "$RUNNER_TEMP/state-clone.log" \
   && [ -d "$STATE/.git" ]; then
  echo "โคลนกิ่ง state แล้ว"
  # ที่เก็บมีสถานะอยู่ ต้องเอากลับเข้าที่ก่อนตัวเก็บเริ่ม ไม่งั้นมันจะเห็นว่าสถานะหาย
  # || true เพราะ set -e จะฆ่าสคริปต์ทิ้งเมื่อกิ่ง state มีอยู่แต่ยังไม่มีไฟล์สถานะในนั้น
  [ -f "$STATE/state.json.gz" ] && cp "$STATE/state.json.gz" "$DATA/state.json.gz" || true
else
  echo "ยังไม่มีกิ่ง state — สร้างใหม่"
  rm -rf "$STATE"; mkdir -p "$STATE"
  git -C "$STATE" init -q -b state
  git -C "$STATE" remote add origin "$REMOTE"
fi

ls -la "$DATA"
