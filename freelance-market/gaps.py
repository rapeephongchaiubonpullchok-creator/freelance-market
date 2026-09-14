#!/usr/bin/env python3
"""ไล่สาย `runs` แล้วบอกว่าตัวเก็บขาดช่วงตรงไหนบ้าง และขาดผิดจากแผนข้อไหน

แผนมีสามจังหวะ และแต่ละจังหวะขาดแล้วเสียของคนละอย่าง:

  ทุก 2 นาที   ฟีดหน้าแรก + งานอายุน้อย — ขาดแล้วเสีย *เส้นเวลาของบิด* กู้ไม่ได้
  ทุก 2 ชม.    งานเปิดค้างทั้งหมด + กวาดช่วง ID + ผลปลายทาง + หน้าเว็บ
  ทุก 6 ชม.    กวาดฟีดทีละหมวดทั้ง 17 หมวด

เส้นแบ่งที่สำคัญที่สุดไม่ใช่จังหวะไหน แต่คือ **ความยาวของช่องว่าง** เทียบกับหน้าต่าง
กวาดช่วง ID ซึ่งกว้างราว 600 ID ≈ 10–12 ชม. ช่องว่างที่สั้นกว่านั้นการกวาด ID ตามเก็บ
ตัวงานกลับมาได้ครบ เสียแค่ความละเอียด ส่วนช่องว่างที่ยาวกว่านั้นทำให้ ID ช่วงกลาง
ไม่มีใครถามมันอีกเลย — หมุดใหม่สุดกระโดดไปข้างหน้าแล้วกวาดย้อนแค่ 600 จากหมุดใหม่

ไม่ยิงเน็ต อ่านจากที่เก็บอย่างเดียว ออกด้วยรหัสไม่เป็นศูนย์เมื่อพบช่องว่างระดับเสียถาวร

  python3 freelance-market/gaps.py --data-dir <โคลนของ repo ข้อมูล>
"""
import argparse, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import read_stream      # noqa: E402

HOUR = 3600




def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(t))


def dur(s):
    """ช่วงเวลาเป็นคำที่อ่านออกโดยไม่ต้องหารเอง"""
    s = int(s)
    if s < 90:
        return f"{s} วิ"
    if s < 5400:
        return f"{s / 60:.0f} นาที"
    return f"{s / HOUR:.1f} ชม."


def phase_gaps(rows, phase, want, slack):
    """ช่วงห่างระหว่างครั้งที่เฟสนี้เดิน เทียบกับที่แผนบอกไว้"""
    at = [r["t"] for r in rows if phase in (r.get("phases") or [])]
    out = []
    for a, b in zip(at, at[1:]):
        if b - a > want * slack:
            out.append((a, b - a))
    return at, out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--tick", type=float, default=120, help="จังหวะเร็วตามแผน (วินาที)")
    ap.add_argument("--slow", type=float, default=2 * HOUR, help="จังหวะช้าตามแผน (วินาที)")
    ap.add_argument("--sweep", type=float, default=6 * HOUR, help="จังหวะกวาดหมวดตามแผน (วินาที)")
    ap.add_argument("--slack", type=float, default=1.5,
                    help="เกินกี่เท่าของแผนจึงนับว่าขาด (ค่าตั้งต้น 1.5)")
    ap.add_argument("--id-window-hours", type=float, default=10.5,
                    help="ความกว้างของหน้าต่างกวาด ID — ช่องว่างที่ยาวกว่านี้เสียตัวงานถาวร")
    o = ap.parse_args()

    damage = []
    rows = read_stream(o.data_dir, "runs", damage)
    if not rows:
        print(f"ไม่พบสาย runs ใน {o.data_dir}")
        return 1

    for d in damage:
        print("  เตือน:", d, file=sys.stderr)

    t0, t1 = rows[0]["t"], rows[-1]["t"]
    span = max(t1 - t0, 1)

    # --- ขอบเขตของแต่ละ job: tick กลับไปนับหนึ่งใหม่ทุกครั้งที่โปรเซสเริ่ม ---
    jobs, cur = [], [rows[0]]
    for r in rows[1:]:
        if r.get("tick", 0) == 1:
            jobs.append(cur); cur = [r]
        else:
            cur.append(r)
    jobs.append(cur)

    print("=" * 74)
    print(f"ช่วงที่มีข้อมูล  {ts(t0)}–{ts(t1)} UTC ({dur(span)} · {len(rows)} รอบ · {len(jobs)} job)")

    print(f"\njob ที่เดินมาแล้ว")
    print(f"  {'เริ่ม':>12} {'จบ':>12} {'ยาว':>10} {'รอบ':>6}  รอบแรกเดินเฟสอะไรบ้าง")
    for j in jobs:
        first = j[0].get("phases") or []
        mark = "ครบทุกเฟส" if "sweep-categories" in first else " ".join(first[:3]) + " …"
        print(f"  {ts(j[0]['t']):>12} {ts(j[-1]['t']):>12} "
              f"{dur(j[-1]['t'] - j[0]['t']):>10} {len(j):>6}  {mark}")

    # --- ช่องว่างของจังหวะ 2 นาที: ทั้งในตัว job เองและระหว่าง job ---
    holes = []
    for a, b in zip(rows, rows[1:]):
        d = b["t"] - a["t"]
        if d > o.tick * o.slack:
            kind = "ระหว่าง job" if b.get("tick", 0) == 1 else "ในตัว job เอง"
            holes.append((a["t"], d, kind))

    print(f"\nช่องว่างของจังหวะ 2 นาที — พบ {len(holes)} ช่อง")
    if holes:
        print(f"  {'เริ่มขาดเมื่อ':>12} {'ยาว':>10}  {'ชนิด':<14} ผลที่ตามมา")
        for t, d, kind in holes:
            if d > o.id_window_hours * HOUR:
                effect = "เสียตัวงานถาวร — เกินหน้าต่างกวาด ID"
            elif d > HOUR:
                effect = "เสียเส้นบิดทั้งช่วง ตัวงานยังกู้ได้"
            else:
                effect = "เสียความละเอียดของบิดบางส่วน"
            print(f"  {ts(t):>12} {dur(d):>10}  {kind:<14} {effect}")
    else:
        print("  ไม่มีเลย — ทุกรอบห่างกันไม่เกินที่แผนกำหนด")

    lost = sum(d for _, d, _ in holes)
    print(f"\n  รวมเวลาที่ขาดไป {dur(lost)} = {100 * lost / span:.1f}% ของช่วงที่มีข้อมูล")

    # --- สองจังหวะช้า ---
    for name, phase, want in (("จังหวะ 2 ชม.", "poll-all", o.slow),
                              ("จังหวะ 6 ชม.", "sweep-categories", o.sweep)):
        at, late = phase_gaps(rows, phase, want, o.slack)
        print(f"\n{name} (`{phase}`) — เดินไปแล้ว {len(at)} ครั้ง", end="")
        if len(at) < 2:
            print(" · ยังน้อยเกินกว่าจะดูช่วงห่างได้")
            continue
        avg = (at[-1] - at[0]) / (len(at) - 1)
        print(f" · ห่างกันเฉลี่ย {dur(avg)} (แผนคือ {dur(want)})")
        if late:
            for t, d in late:
                print(f"  ช้าเกินแผน: หลัง {ts(t)} เว้นไป {dur(d)}")
        else:
            print("  ไม่มีครั้งไหนช้าเกินแผน")

    # --- คำตัดสิน ---
    bad = [h for h in holes if h[1] > o.id_window_hours * HOUR]
    print("=" * 74)
    if bad:
        for t, d, _ in bad:
            print(f"ไม่ผ่าน: ช่องว่าง {dur(d)} ที่ {ts(t)} ยาวเกินหน้าต่างกวาด ID — งานช่วงนั้นหายถาวร")
        return 1
    print(f"ผ่าน — ไม่มีช่องว่างไหนยาวเกิน {o.id_window_hours} ชม. ตัวงานยังตามเก็บกลับได้ครบทุกช่อง")
    return 0


if __name__ == "__main__":
    sys.exit(main())
