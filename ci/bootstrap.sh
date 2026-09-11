#!/usr/bin/env bash
# เตรียมสองโคลนของ repo ข้อมูล: สายข้อมูลอยู่บน main ส่วนไฟล์สถานะอยู่บนกิ่งของตัวเอง
#
# ที่แยกกิ่งเพราะไฟล์สถานะเป็นก้อนบีบอัดที่ถูกเขียนทับทั้งไฟล์ทุกครั้ง ถ้าปนอยู่บน main
# ประวัติของสายข้อมูลจะถูกก้อนใหม่ทับถมจนอ่านส่วนต่างไม่ได้ ทั้งที่สายข้อมูลเป็นไฟล์ต่อท้าย
# ที่ git หาส่วนต่างได้สวย ๆ อยู่แล้ว
#
# กุญแจที่ใช้เป็น deploy key ของ repo ข้อมูลตัวเดียว ไม่ใช่โทเคนของบัญชี ถ้ามันหลุดออกไป
# สิ่งที่ทำได้คือเขียน repo นั้น ไม่มีอะไรอื่นในบัญชีถูกแตะได้เลย
set -euo pipefail

# runner.temp ใช้ในบล็อก env ระดับ job ไม่ได้ จึงตั้งที่นี่แล้วส่งต่อให้ขั้นตอนถัดไป
DATA="${DATA:-$RUNNER_TEMP/data}"
STATE="${STATE:-$RUNNER_TEMP/state}"
KEY="$RUNNER_TEMP/fm_key"

install -m 600 /dev/null "$KEY"
printf '%s\n' "$FM_DATA_SSH_KEY" > "$KEY"
SSH_CMD="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
REMOTE="git@github.com:${DATA_REPO}.git"

{ echo "DATA=$DATA"; echo "STATE=$STATE"
  echo "GIT_SSH_COMMAND=$SSH_CMD"; echo "REMOTE=$REMOTE"; } >> "$GITHUB_ENV"
export GIT_SSH_COMMAND="$SSH_CMD"

# ถามที่เก็บก่อนแตะอะไรทั้งนั้น ไม่งั้นการโคลนที่พังเพราะกุญแจจะหน้าตาเหมือน repo ว่างเปล่า
# แล้วตัวเก็บจะเดินไปทั้ง job ก่อนจะรู้ตอนจบว่า push ไม่ได้มาตั้งแต่แรก
if ! HEADS=$(git ls-remote --heads "$REMOTE" 2>&1); then
  echo "::error::เข้าถึง ${DATA_REPO} ไม่ได้ — กุญแจใน FM_DATA_SSH_KEY ใช้ไม่ได้หรือถูกถอนแล้ว"
  echo "$HEADS"
  exit 1
fi
echo "กุญแจเข้าถึง ${DATA_REPO} ได้"

git config --global user.name  "freelance-market collector"
git config --global user.email "collector@users.noreply.github.com"

# --- สายข้อมูลบน main ---
if grep -q 'refs/heads/main' <<<"$HEADS"; then
  git clone --depth 1 --branch main "$REMOTE" "$DATA"
  echo "โคลน main ของ repo ข้อมูลแล้ว"
else
  echo "ยังไม่มีกิ่ง main — เริ่มใหม่"
  mkdir -p "$DATA"
  git -C "$DATA" init -q -b main
  git -C "$DATA" remote add origin "$REMOTE"
fi
# ไฟล์สถานะอยู่คนละกิ่ง ตัวไล่ push ของ main ต้องไม่แตะมัน
printf 'state.json.gz\nstate.json.gz.tmp\n' > "$DATA/.gitignore"

# --- ไฟล์สถานะบนกิ่ง state ---
if grep -q 'refs/heads/state' <<<"$HEADS"; then
  git clone --depth 1 --branch state "$REMOTE" "$STATE"
  echo "โคลนกิ่ง state แล้ว"
  # ที่เก็บมีสถานะอยู่ ต้องเอากลับเข้าที่ก่อนตัวเก็บเริ่ม ไม่งั้นมันจะเห็นว่าสถานะหาย
  if [ -f "$STATE/state.json.gz" ]; then
    cp "$STATE/state.json.gz" "$DATA/state.json.gz"
    echo "คืนไฟล์สถานะกลับเข้าที่แล้ว ($(stat -c%s "$DATA/state.json.gz") ไบต์)"
  fi
else
  echo "ยังไม่มีกิ่ง state — สร้างใหม่"
  mkdir -p "$STATE"
  git -C "$STATE" init -q -b state
  git -C "$STATE" remote add origin "$REMOTE"
fi

ls -la "$DATA"
