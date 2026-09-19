#!/usr/bin/env python3
"""ตัวอ่านที่ยิงตรงเข้า HTTP แทนการปลุก Claude Code — อ่านพรอมป์จาก stdin พิมพ์ผลออก stdout

สัญญาเดียวกับ `claude-9arm` เป๊ะ คือรับพรอมป์ทาง stdin แล้วพิมพ์ `{"result": "..."}` ออกมา
`run_gate1.py` จึงเรียกตัวนี้แทนได้โดยไม่ต้องแก้อะไร:

  python3 grading/run_gate1.py --out grading/out \
      --reader "python3 grading/reader_api.py" --reader-id <ชื่อรุ่น>

**อ่านค่าตั้งจากไฟล์หรือ environment เท่านั้น ไม่รับคีย์ทาง argument** เพราะ argument
ของกระบวนการอ่านได้จาก `ps` ทั้งเครื่อง และมันติดไปกับบันทึกของเชลล์ด้วย

  FM_READER_BASE   ปลายทาง เช่น https://host/v1
  FM_READER_MODEL  ชื่อรุ่นที่ปลายทางรู้จัก
  FM_READER_KEY    คีย์
  FM_READER_API    openai | anthropic  (ไม่ใส่ = เดาจากปลายทางแล้วลองทั้งสองแบบ)
  FM_READER_TEMP   อุณหภูมิ (ไม่ใส่ = ไม่ส่งไปเลย ใช้ค่าตั้งต้นของปลายทาง)

**เรื่องอุณหภูมิเป็นเรื่องใหญ่ของด่านหนึ่ง** ตั้ง 0 แล้วด่านนี้ผ่านฟรี ๆ โดยไม่ได้บอกอะไรเลย
ค่าที่ใช้วัดต้องเป็นค่าเดียวกับที่จะใช้ตัดเกรดจริง ค่าที่ใช้ถูกพิมพ์ออกมาทุกครั้งที่เรียก
"""
import json, os, sys, time, urllib.error, urllib.request

CFG_FILE = os.path.expanduser(os.environ.get("FM_READER_ENV", "~/.config/fm-grading.env"))
TIMEOUT = 900          # ชุดละ 50 งานอาจใช้เวลาหลายนาที ปลายทางช้ากว่าที่คิดได้เสมอ
RETRIES = 3
KEYS = ("FM_READER_BASE", "FM_READER_MODEL", "FM_READER_KEY", "FM_READER_API", "FM_READER_TEMP")


def load_cfg():
    """ไฟล์ก่อน แล้วให้ environment ทับได้ — ไฟล์คือที่เก็บ environment คือที่แทนเฉพาะกิจ"""
    cfg = {}
    if os.path.exists(CFG_FILE):
        for line in open(CFG_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'\"")
    for k in KEYS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    for k in KEYS[:3]:
        if not cfg.get(k):
            sys.exit(f"ขาด {k} — ตั้งใน {CFG_FILE} หรือใน environment")
    return cfg


def shapes(cfg):
    """รูปแบบที่จะลอง เรียงตามที่เดาว่าน่าจะใช่จากหน้าตาของปลายทาง"""
    want = (cfg.get("FM_READER_API") or "").lower()
    if want in ("openai", "anthropic"):
        return [want]
    base = cfg["FM_READER_BASE"].lower()
    return ["anthropic", "openai"] if "anthropic" in base else ["openai", "anthropic"]


def build(shape, cfg, prompt):
    base = cfg["FM_READER_BASE"].rstrip("/")
    temp = cfg.get("FM_READER_TEMP")
    body = {"model": cfg["FM_READER_MODEL"], "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]}
    if shape == "openai":
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        hdr = {"Authorization": "Bearer " + cfg["FM_READER_KEY"]}
    else:
        url = base if base.endswith("/messages") else base + "/messages"
        hdr = {"x-api-key": cfg["FM_READER_KEY"], "anthropic-version": "2023-06-01"}
    if temp not in (None, ""):
        body["temperature"] = float(temp)
    hdr["Content-Type"] = "application/json"
    return url, body, hdr


def pull_text(shape, data):
    if shape == "openai":
        return data["choices"][0]["message"]["content"]
    # Anthropic คืน content เป็นลิสต์ของบล็อก บล็อกที่ไม่ใช่ text ต้องถูกข้าม ไม่ใช่ต่อรวม
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def call(shape, cfg, prompt):
    url, body, hdr = build(shape, cfg, prompt)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return pull_text(shape, json.loads(r.read().decode()))


def main():
    prompt = sys.stdin.read()
    if not prompt.strip():
        sys.exit("ไม่มีพรอมป์เข้ามาทาง stdin")
    cfg = load_cfg()
    last = None
    for shape in shapes(cfg):
        for attempt in range(RETRIES):
            try:
                text = call(shape, cfg, prompt)
                print(json.dumps({"result": text, "api": shape,
                                  "temperature": cfg.get("FM_READER_TEMP", "ค่าตั้งต้นของปลายทาง")},
                                 ensure_ascii=False))
                return
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400]
                last = f"{shape}: HTTP {e.code} {detail}"
                # 4xx ที่ไม่ใช่การถูกจำกัดอัตรา คือรูปแบบผิดหรือคีย์ผิด ลองซ้ำไม่ช่วย
                if 400 <= e.code < 500 and e.code != 429:
                    break
                time.sleep(5 * (attempt + 1))
            except Exception as e:                       # noqa: BLE001 — ปลายทางพังได้หลายแบบ
                last = f"{shape}: {type(e).__name__} {e}"
                time.sleep(5 * (attempt + 1))
    sys.exit("ยิงไม่ผ่านทุกรูปแบบ ล่าสุด: " + str(last))


if __name__ == "__main__":
    main()
