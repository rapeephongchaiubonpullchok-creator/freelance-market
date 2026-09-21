#!/usr/bin/env bash
# ตัวอ่านที่เป็น Claude Code ห่อโมเดลไว้ — รูปเดียวกับ `claude-9arm` ที่จะใช้ตัดเกรดจริง
#
# เหตุผลที่ต้องเป็นตัวนี้ ไม่ใช่การยิง HTTP ตรง ๆ: harness ใส่พรอมป์ระบบของมันเองเข้าไป
# และมีลูปเอเจนต์ครอบอยู่ ความนิ่งของโมเดลเปล่ากับความนิ่งของโมเดลที่ถูกห่อจึงไม่ใช่
# ตัวเดียวกัน ด่านหนึ่งต้องวัดตัวที่จะตัดเกรดจริง ไม่งั้นวัดไปก็ตอบคำถามผิดข้อ
#
# รับพรอมป์ทาง stdin พิมพ์ผลเป็น JSON ที่มีฟิลด์ result ออก stdout เสียงรบกวนไป stderr
# `run_gate1.py` เรียกตัวนี้ได้เลย:
#
#   python3 grading/run_gate1.py --out grading/out \
#       --reader "bash grading/reader_claude.sh" --reader-id <ชื่อรุ่น>
#
# ค่าตั้งอ่านจาก ~/.config/fm-grading.env (แก้ที่อยู่ได้ด้วย FM_READER_ENV):
#
#   FM_CLAUDE_BASE     ปลายทาง **ระดับราก** ไม่ต้องมี /v1 — claude ต่อ /v1/messages ให้เอง
#   FM_CLAUDE_KEY      คีย์
#   FM_CLAUDE_MODEL    ชื่อรุ่นที่ปลายทางรู้จัก
#   FM_CLAUDE_CONTEXT  ขนาดหน้าต่างจริงของรุ่นนั้น (ไม่ใส่ = 128000)
#
# คีย์เข้าทางไฟล์เท่านั้น ไม่เคยเข้าทาง argument เพราะ argument อ่านได้จาก ps ทั้งเครื่อง
set -euo pipefail

CFG="${FM_READER_ENV:-$HOME/.config/fm-grading.env}"
[ -f "$CFG" ] || { echo "ไม่มีไฟล์ค่าตั้ง $CFG" >&2; exit 1; }
set -a; . "$CFG"; set +a

for v in FM_CLAUDE_BASE FM_CLAUDE_KEY FM_CLAUDE_MODEL; do
  [ -n "${!v:-}" ] || { echo "ขาด $v ใน $CFG" >&2; exit 1; }
done

# ชื่อรุ่นของปลายทางอื่นไม่อยู่ในแค็ตตาล็อกของ claude รุ่นนี้ ซึ่งไม่ได้ทำให้เรียกไม่ได้
# แต่ถ้าไม่บอกขนาดหน้าต่าง มันจะเดาเอาว่า 200k แล้วย่อบทสนทนาตามสมมติฐานที่ผิด
export ANTHROPIC_BASE_URL="$FM_CLAUDE_BASE"
export ANTHROPIC_AUTH_TOKEN="$FM_CLAUDE_KEY"
export CLAUDE_CODE_MAX_CONTEXT_TOKENS="${FM_CLAUDE_CONTEXT:-128000}"

# งานนี้เป็นการอ่านแล้วตอบล้วน ๆ ไม่มีเหตุให้แตะเครื่องมือสักตัว ปิดไว้ทั้งหมดเพื่อไม่ให้
# มันไปค้างรอขออนุมัติกลางชุด และไม่ให้ MCP ของเครื่องนี้หลุดเข้าไปในบริบทของมัน
# **ต้องยิงแบบสตรีมเท่านั้น** วัดแล้ว 2026-09-21: ตัวกลางหน้าเกตเวย์ตัดสายที่ไม่มีอะไรวิ่ง
# ทิ้งด้วยรหัส 524 และเพดานนั้นต่ำถึง 125 วินาทีตอนเครื่องหลังบ้านยุ่ง ซึ่งสั้นกว่าเวลาที่
# งานชิ้นเดียวใช้ (586 วินาทีในการวัดเดียวกัน) แบบสตรีมมีไบต์วิ่งตลอดจึงไม่ถูกตัด — วิ่งผ่าน
# 30 นาทีได้โดยไม่มีอะไรมาตัด ส่วน stdout ที่ออกจากตัวนี้ยังเป็น JSON ก้อนเดียวเหมือนเดิม
# เพราะแถวสุดท้ายของสตรีมคือแถว result ที่ `run_gate1.py` อ่านอยู่แล้ว
claude \
  --model "$FM_CLAUDE_MODEL" \
  --disallowedTools Bash Read Edit Write Glob Grep WebFetch WebSearch Task NotebookEdit \
  --strict-mcp-config \
  --no-session-persistence \
  -p --output-format stream-json --include-partial-messages --verbose \
  | python3 -c '
import json, sys
last = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "result":
        last = ev
print(json.dumps(last or {"result": "", "note": "สตรีมจบโดยไม่มีแถว result"}, ensure_ascii=False))
'
exit "${PIPESTATUS[0]}"
