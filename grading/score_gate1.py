#!/usr/bin/env python3
"""อ่านผลด่านหนึ่งแล้วตอบว่าผู้อ่านนิ่งพอไหม และถ้าไม่นิ่ง ไม่นิ่งตรงไหน

เกณฑ์ผ่านของงานหนึ่งชิ้นคือ **ลงขั้นเดิมอย่างน้อยสี่ในห้ารอบ** ซึ่งเป็นเกณฑ์ที่ออกแบบไว้แต่แรก
ส่วนเกณฑ์ว่าทั้งชุดต้องผ่านกี่ % ยังไม่เคยถูกกำหนด ค่าตั้งต้น 80% ในนี้เป็นการเดา
แก้ได้ด้วย --pass-share และต้องถูกยืนยันก่อนเอาไปใช้ตัดสินจริง

ตัวเลขที่ต้องอ่านคู่กันเสมอ:
  ความครบ   — ตัวอ่านตอบครบทุกชิ้นไหม ชุดที่ตอบไม่ครบแปลว่าชุดใหญ่เกิน ไม่ใช่บันไดพัง
  ความนิ่ง  — สัดส่วนงานที่ลงขั้นเดิม ≥4/5 แยกสองแกน
  ตำแหน่ง   — งานท้ายชุดถูกตัดสินหยาบกว่างานต้นชุดจริงไหม ถ้าใช่ ทางแก้คือลดขนาดชุด
  ตกขอบ     — สัดส่วน off และงานที่แกว่งระหว่าง off กับขั้นจริง ซึ่งเป็นความกำกวมคนละพันธุ์

  python3 grading/score_gate1.py --out grading/out
"""
import argparse, collections, json, os, sys

ROUNDS = 5
AXES = (("k", "แกน K พื้นความสามารถ"), ("d", "แกน D สิ่งที่ส่งมอบ"))


def mode(vals):
    """ค่าที่ซ้ำมากสุด — เสมอกันให้คืนตัวที่เรียงแล้วมาก่อน เพื่อให้ผลไม่ขึ้นกับลำดับที่อ่านไฟล์"""
    c = collections.Counter(vals)
    top = max(c.values())
    return sorted([v for v, n in c.items() if n == top], key=str)[0], top


def bar(share, width=28):
    return "█" * round(share * width) + "·" * (width - round(share * width))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pass-share", type=float, default=0.80)
    a = ap.parse_args()

    path = os.path.join(a.out, "gate1_grades.jsonl")
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not rows:
        sys.exit("ไม่มีแถวใน " + path)
    size = json.load(open(os.path.join(a.out, "sample.json"), encoding="utf-8"))["size"]
    revs = {r["ladder_rev"] for r in rows}
    readers = {r["reader"] for r in rows}
    print(f"ไม้บรรทัด rev {', '.join(sorted(revs))} · ตัวอ่าน {', '.join(sorted(readers))}")
    if len(revs) > 1 or len(readers) > 1:
        sys.exit("ผลนี้ปนหลายไม้บรรทัดหรือหลายตัวอ่าน ด่านหนึ่งเทียบแบบนี้ไม่ได้")

    by_round = collections.Counter(r["round"] for r in rows)
    print(f"\n## ความครบ  ชุดละ {size} ชิ้น {len(by_round)} รอบ")
    holes = 0
    for r in sorted(by_round):
        n = by_round[r]
        holes += size - n
        print(f"  รอบ {r}: {n}/{size} {bar(n/size)}")
    if holes:
        print(f"  ตอบไม่ครบรวม {holes} ช่อง — ชุดใหญ่เกินหน้าต่างหรือคำตอบผิดรูป ให้ลดขนาดชุดก่อนสรุปอย่างอื่น")

    ans = collections.defaultdict(dict)                 # ans[axis][n] = {round: value}
    for r in rows:
        for ax, _ in AXES:
            ans[ax].setdefault(r["n"], {})[r["round"]] = r[ax]

    verdicts = {}
    for ax, label in AXES:
        stable, unstable, off_mixed = [], [], []
        for n in range(1, size + 1):
            vals = list(ans[ax].get(n, {}).values())
            if not vals:
                continue
            m, cnt = mode(vals)
            (stable if cnt >= 4 else unstable).append((n, m, cnt, vals))
            if "off" in vals and any(v != "off" for v in vals):
                off_mixed.append(n)
        total = len(stable) + len(unstable)
        share = len(stable) / total if total else 0.0
        verdicts[ax] = share
        print(f"\n## ความนิ่ง — {label}")
        print(f"  ลงขั้นเดิม ≥4/5: {len(stable)}/{total} = {share:.0%} {bar(share)}")
        spread = collections.Counter(c for _, _, c, _ in stable + unstable)
        print("  กระจายตามจำนวนรอบที่ตรงกัน: " +
              "  ".join(f"{c}/5 → {spread[c]}" for c in sorted(spread, reverse=True)))
        if off_mixed:
            print(f"  แกว่งระหว่าง off กับขั้นจริง {len(off_mixed)} ชิ้น: {off_mixed[:12]}")
        if unstable:
            print("  ชิ้นที่ไม่นิ่ง (n: คำตอบทั้งห้ารอบ)")
            for n, m, c, vals in unstable[:15]:
                far = " ← ห่างเกินหนึ่งขั้น" if _far(vals) else ""
                print(f"    {n}: {vals}{far}")
            if len(unstable) > 15:
                print(f"    ... อีก {len(unstable)-15} ชิ้น")

    print("\n## ตำแหน่งในชุด — งานท้ายชุดถูกตัดสินหยาบกว่าไหม")
    third = max(1, size // 3)
    for ax, label in AXES:
        buckets = collections.defaultdict(lambda: [0, 0])
        for r in rows:
            vals = list(ans[ax].get(r["n"], {}).values())
            m, _ = mode(vals)
            b = "ต้นชุด" if r["pos"] <= third else ("ท้ายชุด" if r["pos"] > size - third else "กลางชุด")
            buckets[b][1] += 1
            if r[ax] != m:
                buckets[b][0] += 1
        parts = []
        for b in ("ต้นชุด", "กลางชุด", "ท้ายชุด"):
            bad, tot = buckets[b]
            parts.append(f"{b} {bad/tot:.0%}" if tot else f"{b} —")
        print(f"  {label}: คำตอบที่ต่างจากค่าที่ตอบบ่อยสุดของชิ้นนั้น · " + "  ".join(parts))

    print("\n## ตกขอบ")
    for ax, label in AXES:
        c = collections.Counter(r[ax] for r in rows)
        tot = sum(c.values())
        print(f"  {label}: " + "  ".join(f"{k}={c[k]} ({c[k]/tot:.0%})" for k in sorted(c, key=str)))

    ok = all(v >= a.pass_share for v in verdicts.values()) and holes == 0
    print("\n## ผล")
    if ok:
        print(f"  ผ่าน — ทั้งสองแกนนิ่งเกิน {a.pass_share:.0%} และตัวอ่านตอบครบทุกรอบ")
        print("  ขั้นต่อไปคือตัดรายชื่อวิชาชีพจากการนับแท็กที่อยู่ด้วยกันในงานจริง")
    else:
        print(f"  ไม่ผ่าน — ต้องลดขนาดชุดหรือซอยคำถามให้ปิดขึ้น **ห้ามปรับบันไดเพราะผลด่านนี้**")
        print("  บันไดจะถูกแก้ด้วยผลของด่านสองและด่านสามเท่านั้น")
    sys.exit(0 if ok else 1)


def _far(vals):
    nums = [v for v in vals if isinstance(v, int)]
    return bool(nums) and max(nums) - min(nums) > 1


if __name__ == "__main__":
    main()
