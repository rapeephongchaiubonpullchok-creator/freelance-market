#!/usr/bin/env python3
"""ด่านหนึ่ง: ตัดเกรดชุดเดิมห้ารอบ สลับตำแหน่งในชุดทุกรอบ แล้วเก็บคำตอบดิบไว้ทุกรอบ

ด่านนี้ถามคำถามเดียว — **ผู้อ่านคนเดิมให้คำตอบเดิมไหม** ไม่ได้ถามว่าไม้บรรทัดถูกหรือผิด
ซึ่งเป็นคำถามของด่านสองกับด่านสาม ถ้าด่านนี้ไม่ผ่าน บันไดที่สร้างไว้จะไม่มีที่ใช้
ทางแก้เมื่อไม่ผ่านคือ **ลดขนาดชุดหรือซอยคำถามให้ปิดขึ้น ไม่ใช่ปรับบันได**

**ทำไมต้องสลับตำแหน่ง** เพราะงานท้ายชุดมักถูกตัดสินหยาบกว่างานต้นชุด ถ้าเรียงเหมือนเดิม
ทั้งห้ารอบ ความเอียงตามตำแหน่งจะกลายเป็นความนิ่งปลอม — งานท้ายชุดจะได้คำตอบผิดแบบเดิม
ซ้ำ ๆ แล้วนับเป็นผ่าน รอบแรกใช้ลำดับเดิมไว้เทียบ อีกสี่รอบสลับด้วย seed ที่บันทึกไว้

ตัวอ่านเป็น Claude Code ทั้งตัว ไม่ใช่ API — เรียกทีละงานไม่ได้ ค่าโสหุ้ยของการปลุกเอเจนต์
กินทุกอย่าง ทั้งชุดจึงถูกยัดไปในการเรียกครั้งเดียวต่อหนึ่งรอบ

  python3 grading/run_gate1.py --out grading/out --ladder grading/ladders/graphic-design.md
  python3 grading/run_gate1.py --out grading/out --dry-run > /tmp/prompt.txt   # ดูพรอมป์ก่อนยิง
"""
import argparse, hashlib, json, os, random, shlex, subprocess, sys, time

ROUNDS = 5

HEAD = """คุณกำลังจับงานฟรีแลนซ์วางลงบันไดสองใบที่แช่แข็งแล้ว ห้ามสร้างขั้นใหม่ ห้ามใช้ครึ่งขั้น

{ladder}

---

ข้างล่างคืองาน {count} ชิ้น แต่ละชิ้นมีหมายเลข n แท็กของเว็บ และคำอธิบายที่ลูกค้าเขียน

ตอบทุกชิ้นให้ครบ {count} ชิ้น หนึ่งบรรทัดต่อหนึ่งชิ้น เป็น JSON ล้วน ไม่ต้องอธิบาย ไม่ต้องขึ้นหัวข้อ:
{{"n": <หมายเลข>, "k": <1-5 หรือ "off">, "d": <1-5 หรือ "off">}}

k คือขั้นบนแกน K และ d คือขั้นบนแกน D เลือกจากขั้นที่มีตัวอย่างยึดไว้แล้วเท่านั้น
งานที่ไม่ใช่งานกราฟิกดีไซน์ตอบ "off" ทั้งสองแกน ห้ามเดายัดลงขั้นที่ใกล้ที่สุด

---
"""


def build_prompt(ladder, items):
    body = []
    for it in items:
        body.append(f"n={it['n']}\nแท็ก: {', '.join(it['tags'])}\n{it['desc']}\n")
    return HEAD.format(ladder=ladder.strip(), count=len(items)) + "\n".join(body)


def orders(size, seed):
    """ลำดับของทุกรอบ — รอบแรกคือลำดับเดิม อีกสี่รอบสลับ"""
    base = list(range(size))
    out = [list(base)]
    rnd = random.Random(seed)
    for _ in range(ROUNDS - 1):
        o = list(base)
        rnd.shuffle(o)
        out.append(o)
    return out


def parse(text, size):
    """เก็บทุก object ที่มี n/k/d ทนคำพูดที่ปนมารอบ ๆ และทน ```json ที่ครอบไว้

    คำตอบซ้ำหมายเลขเดิมให้ยึด **อันแรก** เพราะอันหลังมักเป็นการสรุปซ้ำท้ายคำตอบ
    ซึ่งไม่ใช่การตัดสินใหม่ คำตอบที่หายไปเลยถูกนับเป็นรูและรายงานแยก ห้ามเติมแทน
    """
    out, seen = {}, set()
    for raw in text.splitlines():
        s = raw.strip().strip("`").strip(",")
        if not s.startswith("{"):
            continue
        try:
            r = json.loads(s)
        except ValueError:
            continue
        n = r.get("n")
        if not isinstance(n, int) or not 1 <= n <= size or n in seen:
            continue
        k, d = r.get("k"), r.get("d")
        norm = lambda v: v if v in (1, 2, 3, 4, 5) else ("off" if str(v).lower() == "off" else None)
        if norm(k) is None or norm(d) is None:
            continue
        seen.add(n)
        out[n] = {"k": norm(k), "d": norm(d)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ladder", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "ladders", "graphic-design.md"))
    ap.add_argument("--reader", default="claude-9arm",
                    help="คำสั่งของตัวอ่าน พรอมป์ถูกป้อนทาง stdin")
    ap.add_argument("--reader-id", default="qwen3.6-35b-a3b",
                    help="ชื่อรุ่นที่จะบันทึกลงทุกแถว")
    ap.add_argument("--order-seed", type=int, default=20260918)
    ap.add_argument("--dry-run", action="store_true", help="พิมพ์พรอมป์รอบแรกแล้วออก ไม่ยิงตัวอ่าน")
    a = ap.parse_args()

    sample = json.load(open(os.path.join(a.out, "sample.json"), encoding="utf-8"))
    items, size = sample["items"], sample["size"]
    ladder = open(a.ladder, encoding="utf-8").read()
    rev = hashlib.sha256(ladder.encode()).hexdigest()[:12]

    if a.dry_run:
        print(build_prompt(ladder, items))
        return

    cmd = shlex.split(a.reader) + ["-p", "--output-format", "json"]
    rows, raw_dir = [], os.path.join(a.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    for r, order in enumerate(orders(size, a.order_seed), start=1):
        shown = [items[i] for i in order]
        prompt = build_prompt(ladder, shown)
        t0 = time.time()
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
        dt = time.time() - t0
        open(os.path.join(raw_dir, f"round{r}.txt"), "w", encoding="utf-8").write(p.stdout)
        if p.returncode != 0:
            sys.exit(f"รอบ {r}: ตัวอ่านออกด้วยรหัส {p.returncode}\n{p.stderr[:2000]}")
        # ตัวอ่านทั้งสองแบบห่อคำตอบไว้ในฟิลด์ result เหมือนกัน ตัวที่ยิง HTTP เองแนบ
        # รูปแบบ API กับอุณหภูมิที่ใช้มาด้วย ซึ่งต้องติดไปกับทุกแถว ไม่งั้นผลของสองรอบ
        # ที่ยิงคนละอุณหภูมิจะถูกเอามาเทียบกันโดยไม่มีอะไรฟ้อง
        text, extra = p.stdout, {}
        try:
            payload = json.loads(p.stdout)
            text = payload.get("result", p.stdout)
            extra = {k: payload[k] for k in ("api", "temperature") if k in payload}
        except ValueError:
            pass
        got = parse(text, size)
        # ตำแหน่งที่งานชิ้นนั้น *ถูกเห็น* ในรอบนี้ คือสิ่งที่ต้องบันทึก ไม่ใช่ลำดับในไฟล์ชุด
        pos = {items[i]["n"]: idx + 1 for idx, i in enumerate(order)}
        for n, v in got.items():
            rows.append({"round": r, "n": n, "pos": pos[n], "k": v["k"], "d": v["d"],
                         "ladder_rev": rev, "reader": a.reader_id, **extra})
        print(f"รอบ {r}: ตอบมา {len(got)}/{size} ชิ้น ใช้เวลา {dt/60:.1f} นาที")

    with open(os.path.join(a.out, "gate1_grades.jsonl"), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"เขียนแล้ว {a.out}/gate1_grades.jsonl · ไม้บรรทัด rev {rev} · ตัวอ่าน {a.reader_id}")
    print(f"ต่อด้วย: python3 grading/score_gate1.py --out {a.out}")


if __name__ == "__main__":
    main()
