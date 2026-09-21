#!/usr/bin/env bash
# ตัวอ่านที่ใช้บัญชี claude.ai ของผู้ใช้ (แพ็กเกจรายเดือน) — ไม่แตะเกตเวย์ที่บ้าน
# ต่างจาก reader_claude.sh แค่ตรงที่ไม่ตั้ง ANTHROPIC_* ทั้งสามตัว
set -uo pipefail
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY CLAUDE_CODE_MAX_CONTEXT_TOKENS
claude \
  --disallowedTools Bash Read Edit Write Glob Grep WebFetch WebSearch Task NotebookEdit \
  --strict-mcp-config \
  --no-session-persistence \
  -p --output-format stream-json --include-partial-messages --verbose \
  | python3 -c '
import json, sys
last = None
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: ev = json.loads(line)
    except ValueError: continue
    if ev.get("type") == "result": last = ev
print(json.dumps(last or {"result": "", "note": "ไม่มีแถว result"}, ensure_ascii=False))
'
