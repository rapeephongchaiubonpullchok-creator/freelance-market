#!/usr/bin/env python3
"""อ่านสาย `runs` ของการรันยาว แล้วตอบว่าโดนจำกัดอัตราหรือถูกบล็อกไหม

ข้อสงสัยที่สคริปต์นี้ตอบคือข้อเดียว: การยิงระดับหลายพันรีเควสต์ต่อวันติดต่อกัน
ทำให้ถูกกันหรือถูกหน่วงหรือเปล่า ซึ่ง `probe.py` ตอบไม่ได้เพราะมันยิงแค่ 8 ครั้งติดกัน

ไม่ยิงเน็ตเอง อ่านจากที่เก็บอย่างเดียว ตัวเก็บจริงคือตัวสร้างภาระ เพราะส่วนผสมของ
รีเควสต์ต้องเหมือนของจริงถึงจะตอบได้ ออกด้วยรหัสไม่เป็นศูนย์เมื่อพบสัญญาณว่าถูกกัน
เพื่อให้ Actions ขึ้นแดงโดยไม่ต้องมีคนไปนั่งอ่าน

  python3 freelance-market/soak_report.py --data-dir $RUNNER_TEMP/fmdata
"""
import argparse, glob, gzip, json, os, sys, time

BLOCKY = ("403", "429", "451")          # รหัสที่แปลว่าถูกกัน ไม่ใช่เว็บสะดุด
HOUR = 3600


def load_runs(root):
    rows = []
    for p in sorted(glob.glob(os.path.join(root, "*", "runs.jsonl.gz"))):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return sorted(rows, key=lambda r: r.get("t", 0))


def bucket(rows, t0):
    """รวมเป็นถังละชั่วโมง — การถูกหน่วงแบบค่อยเป็นค่อยไปเห็นได้จากการเทียบถังต้นกับถังท้าย"""
    out = {}
    for r in rows:
        h = int((r.get("t", t0) - t0) // HOUR)
        b = out.setdefault(h, {"ticks": 0, "req": 0, "secs": 0.0, "retry": 0,
                               "fail": 0, "codes": {}, "blocked": 0, "errors": 0})
        n = r.get("net") or {}
        b["ticks"] += 1
        b["req"] += n.get("requests", 0)
        b["secs"] += n.get("secs", 0.0)
        b["retry"] += n.get("retries", 0)
        b["fail"] += n.get("failed", 0)
        for c, k in (n.get("codes") or {}).items():
            b["codes"][c] = b["codes"].get(c, 0) + k
        if r.get("blocked"):
            b["blocked"] += 1
        if r.get("error"):
            b["errors"] += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--max-fail-pct", type=float, default=2.0,
                    help="สัดส่วนรีเควสต์ที่ยิงไม่สำเร็จซึ่งยังถือว่าเป็นเน็ตสะดุด (ค่าตั้งต้น 2%%)")
    ap.add_argument("--max-slowdown", type=float, default=2.0,
                    help="เวลาต่อรีเควสต์ของชั่วโมงท้ายเทียบชั่วโมงแรกที่ยังยอมรับได้")
    o = ap.parse_args()

    rows = load_runs(o.data_dir)
    if not rows:
        print(f"ไม่พบสาย runs ใน {o.data_dir} — การรันไม่ได้เกิดขึ้นจริง")
        return 1

    t0, t1 = rows[0]["t"], rows[-1]["t"]
    span = max(t1 - t0, 1)
    tot = {"req": 0, "secs": 0.0, "retry": 0, "fail": 0}
    codes = {}
    for r in rows:
        n = r.get("net") or {}
        tot["req"] += n.get("requests", 0)
        tot["secs"] += n.get("secs", 0.0)
        tot["retry"] += n.get("retries", 0)
        tot["fail"] += n.get("failed", 0)
        for c, k in (n.get("codes") or {}).items():
            codes[c] = codes.get(c, 0) + k
    per_day = tot["req"] * 86400 / span

    print("=" * 70)
    print(f"ช่วงเวลา   {time.strftime('%Y-%m-%d %H:%M', time.gmtime(t0))}–"
          f"{time.strftime('%H:%M', time.gmtime(t1))} UTC ({span / HOUR:.2f} ชม. · {len(rows)} รอบ)")
    # รอบแรกกวาดทั้ง 17 หมวดจนถึงก้น จึงหนักกว่ารอบอื่นหลายสิบเท่า และดันค่าเฉลี่ยของช่วงสั้นให้เพี้ยน
    rate = f"{tot['req'] / (span / HOUR):.0f}/ชม. → เทียบเป็น {per_day:.0f}/วัน (รวมรอบกวาดหมวดตอนเริ่ม)" \
        if span >= HOUR else "ช่วงสั้นเกินกว่าจะเทียบเป็นอัตราต่อวันได้"
    print(f"รีเควสต์   {tot['req']} ครั้ง = {rate}")
    print(f"รหัสที่ได้ {' '.join(f'{c}×{k}' for c, k in sorted(codes.items()))}")
    print(f"ยิงซ้ำ {tot['retry']} · ยิงไม่สำเร็จ {tot['fail']} "
          f"({100 * tot['fail'] / max(tot['req'], 1):.2f}% ของรีเควสต์)")

    print("\nต่อชั่วโมง (ms/รีเควสต์ คือเวลาที่เว็บใช้ตอบ ไม่รวมจังหวะรอของเราเอง)")
    print(f"  {'ชม.':>4} {'รอบ':>5} {'รีเควสต์':>9} {'ms/รีเควสต์':>12} {'ซ้ำ':>5} {'พลาด':>5}  รหัสที่ไม่ใช่ 200")
    b = bucket(rows, t0)
    for h in sorted(b):
        x = b[h]
        ms = 1000 * x["secs"] / x["req"] if x["req"] else 0
        odd = " ".join(f"{c}×{k}" for c, k in sorted(x["codes"].items()) if c != "200") or "-"
        print(f"  {h:>4} {x['ticks']:>5} {x['req']:>9} {ms:>12.0f} {x['retry']:>5} {x['fail']:>5}  {odd}")

    # --- คำตัดสิน ---
    fails = []
    hit = {c: codes[c] for c in BLOCKY if c in codes}
    if hit:
        fails.append("เจอรหัสที่แปลว่าถูกกัน: " + " ".join(f"{c}×{k}" for c, k in hit.items()))
    nblocked = sum(1 for r in rows if r.get("blocked"))
    if nblocked:
        fails.append(f"ตัวเก็บประกาศว่าถูกบล็อก {nblocked} รอบ")
    fail_pct = 100 * tot["fail"] / max(tot["req"], 1)
    if fail_pct > o.max_fail_pct:
        fails.append(f"ยิงไม่สำเร็จ {fail_pct:.2f}% เกินเพดาน {o.max_fail_pct}%")
    full = [h for h in sorted(b) if b[h]["req"] >= 20]
    if len(full) >= 2:
        first, last = b[full[0]], b[full[-1]]
        m0 = 1000 * first["secs"] / first["req"]
        m1 = 1000 * last["secs"] / last["req"]
        if m0 > 0 and m1 / m0 > o.max_slowdown:
            fails.append(f"เวลาต่อรีเควสต์โตจาก {m0:.0f} เป็น {m1:.0f} ms "
                         f"({m1 / m0:.1f} เท่า) — น่าจะถูกหน่วงแบบไม่ประกาศ")
    else:
        print("\nหมายเหตุ: ข้อมูลไม่ถึงสองชั่วโมงเต็ม จึงยังเทียบต้น–ท้ายเพื่อหาการหน่วงไม่ได้")

    print("=" * 70)
    if fails:
        for f in fails:
            print("ไม่ผ่าน: " + f)
        return 1
    print(f"ผ่าน — ยิงต่อเนื่อง {span / HOUR:.2f} ชม. {tot['req']} รีเควสต์ ไม่มีสัญญาณว่าถูกกันหรือถูกหน่วง")
    return 0


if __name__ == "__main__":
    sys.exit(main())
