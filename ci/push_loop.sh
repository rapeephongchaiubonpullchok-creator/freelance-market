#!/usr/bin/env bash
# ส่งสายข้อมูลขึ้น main ทุก 15 นาทีระหว่างที่ตัวเก็บวิ่ง
#
# 15 นาทีคือเพดานของสิ่งที่ยอมเสียเมื่อ job ถูกฆ่ากลางคัน ต่างจากไฟล์สถานะที่ commit ตอนจบเท่านั้น
# สองอย่างนี้ไปคนละจังหวะกันได้เพราะสายข้อมูลเป็นไฟล์ต่อท้ายที่ git หาส่วนต่างได้ ส่วนสถานะไม่ใช่
#
# push ที่พังต้องไม่เงียบ แต่ก็ต้องไม่ฆ่าตัวเก็บทิ้ง — เก็บข้อมูลต่อไปได้ดีกว่าหยุด จึงจดไว้ใน
# แฟ้มร่องรอยแล้วให้ขั้นตอนสุดท้ายของ job เป็นคนทำให้แดง
set -uo pipefail

while sleep 900; do
  git -C "$DATA" add -A
  git -C "$DATA" diff --cached --quiet && continue
  git -C "$DATA" commit -qm "data $(date -u '+%Y-%m-%d %H:%M') UTC"
  if ! git -C "$DATA" push -q origin main 2>&1 | tee -a "$RUNNER_TEMP/push.log"; then
    date -u '+%Y-%m-%d %H:%M:%S UTC push ล้มเหลว' >> "$RUNNER_TEMP/push-failed"
    tail -20 "$RUNNER_TEMP/push.log" >> "$RUNNER_TEMP/push-failed" 2>/dev/null || true
  fi
done
