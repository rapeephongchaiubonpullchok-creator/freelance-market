#!/usr/bin/env python3
"""ด่านหนึ่ง: ตัดเกรดชุดเดิมห้ารอบ สลับตำแหน่งในชุดทุกรอบ แล้วเก็บคำตอบดิบไว้ทุกรอบ

ด่านนี้ถามคำถามเดียว — **ผู้อ่านคนเดิมให้คำตอบเดิมไหม** ไม่ได้ถามว่าไม้บรรทัดถูกหรือผิด
ซึ่งเป็นคำถามของด่านสองกับด่านสาม ถ้าด่านนี้ไม่ผ่าน บันไดที่สร้างไว้จะไม่มีที่ใช้
ทางแก้เมื่อไม่ผ่านคือ **ลดขนาดชุดหรือซอยคำถามให้ปิดขึ้น ไม่ใช่ปรับบันได**

**ทำไมต้องสลับตำแหน่ง** เพราะงานท้ายชุดมักถูกตัดสินหยาบกว่างานต้นชุด ถ้าเรียงเหมือนเดิม
ทั้งห้ารอบ ความเอียงตามตำแหน่งจะกลายเป็นความนิ่งปลอม — งานท้ายชุดจะได้คำตอบผิดแบบเดิม
ซ้ำ ๆ แล้วนับเป็นผ่าน รอบแรกใช้ลำดับเดิมไว้เทียบ อีกสี่รอบสลับด้วย seed ที่บันทึกไว้

ตัวอ่านเป็น Claude Code ทั้งตัว ไม่ใช่ API — เรียกทีละงานไม่ได้ ค่าโสหุ้ยของการปลุกเอเจนต์
กินทุกอย่าง ทั้งชุดจึงถูกยัดไปในการเรียกครั้งเดียวต่อหนึ่งรอบ ตัวอ่านที่ใช้จริงถูกบันทึกลงทุกแถว
ทั้งชื่อรุ่นและคำสั่งที่เรียก เพราะโมเดลตัวเดียวกันที่ถูก harness ห่อกับที่ยิงตรงเข้า API
ไม่ใช่ผู้อ่านคนเดียวกัน และผลของสองแบบนั้นเอามาเทียบกันไม่ได้

  python3 grading/run_gate1.py --out grading/out --ladder grading/ladders/graphic-design.md
  python3 grading/run_gate1.py --out grading/out --dry-run > /tmp/prompt.txt   # ดูพรอมป์ก่อนยิง
"""
import argparse, concurrent.futures, hashlib, json, os, random, shlex, subprocess, threading, time

ROUNDS = 5

HEAD = """คุณกำลังจับงานฟรีแลนซ์วางลงบันไดสองใบที่แช่แข็งแล้ว ห้ามสร้างขั้นใหม่ ห้ามใช้ครึ่งขั้น

{ladder}

---

ข้างล่างคืองาน {count} ชิ้น แต่ละชิ้นมีหมายเลข n แท็กของเว็บ และคำอธิบายที่ลูกค้าเขียน

ตอบทุกชิ้นให้ครบ {count} ชิ้น หนึ่งบรรทัดต่อหนึ่งชิ้น เป็น JSON ล้วน ไม่ต้องอธิบาย ไม่ต้องขึ้นหัวข้อ

ตัดสินสองขั้นตามลำดับนี้ทุกชิ้น
1) งานนี้เป็นงานกราฟิกดีไซน์ไหม ถ้าไม่ใช่ ตอบบรรทัดเดียวว่า {{"n": <หมายเลข>, "fit": 0}}
   แล้วข้ามไปชิ้นถัดไปทันที ห้ามเดายัดลงขั้นที่ใกล้ที่สุด
2) ถ้าใช่ ตอบ {{"n": <หมายเลข>, "fit": 1, "k": <1-5>, "d": <1-5>}}

k คือขั้นบนแกน K และ d คือขั้นบนแกน D เลือกจากขั้นที่มีตัวอย่างยึดไว้แล้วเท่านั้น

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
        norm = lambda v: v if v in (1, 2, 3, 4, 5) else ("off" if str(v).lower() == "off" else None)
        fit = r.get("fit")
        # ไม่เข้าวิชาชีพ = จบแค่บรรทัดเดียว ไม่ต้องมีสองแกน และต้องไม่ถูกทิ้งเป็นรู
        # เพราะ "ไม่ใช่งานสายนี้" เป็นคำตอบ ไม่ใช่การตอบไม่ได้
        if fit in (0, False, "0"):
            seen.add(n)
            out[n] = {"fit": 0, "k": "off", "d": "off"}
            continue
        k, d = norm(r.get("k")), norm(r.get("d"))
        if k is None or d is None:
            continue
        seen.add(n)
        # คำตอบรูปเก่าที่ไม่มี fit ยังอ่านได้ — "off" ทั้งสองแกนคือคำตอบเดียวกับ fit=0
        out[n] = {"fit": 1 if fit in (1, True, "1") else (0 if k == "off" and d == "off" else None),
                  "k": k, "d": d}
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
    ap.add_argument("--resume", action="store_true",
                    help="ข้ามรอบที่มีผลอยู่แล้วในไฟล์ผล ใช้เมื่อรันครั้งก่อนถูกตัดกลางคัน")
    ap.add_argument("--chunk", type=int, default=10,
                    help="จำนวนงานต่อการเรียกหนึ่งครั้ง — ใหญ่ไปแล้วเกตเวย์ตอบไม่ทันก่อนถูกตัดสาย")
    ap.add_argument("--parallel", type=int, default=3,
                    help="ยิงพร้อมกันกี่สาย — วัดแล้วเกตเวย์รับได้ราว 3-4 เกินกว่านั้นถูกปฏิเสธทันที")
    ap.add_argument("--tries", type=int, default=4, help="ยิงซ้ำสูงสุดกี่ครั้งต่อชุดย่อย")
    ap.add_argument("--dry-run", action="store_true", help="พิมพ์พรอมป์รอบแรกแล้วออก ไม่ยิงตัวอ่าน")
    a = ap.parse_args()

    sample = json.load(open(os.path.join(a.out, "sample.json"), encoding="utf-8"))
    items, size = sample["items"], sample["size"]
    ladder = open(a.ladder, encoding="utf-8").read()
    rev = hashlib.sha256(ladder.encode()).hexdigest()[:12]
    # พรอมป์เปลี่ยน = คำตอบเทียบข้ามรุ่นไม่ได้ เหมือนไม้บรรทัดเปลี่ยน จึงต้องมีลายนิ้วมือของตัวเอง
    prompt_rev = hashlib.sha256(HEAD.encode()).hexdigest()[:12]

    if a.dry_run:
        print(build_prompt(ladder, items))
        return

    cmd = shlex.split(a.reader) + ["-p", "--output-format", "json"]
    raw_dir = os.path.join(a.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    grades = os.path.join(a.out, "gate1_grades.jsonl")

    # ชุดย่อยคือหน่วยของทุกอย่าง — ของการยิง การเขียนลงดิสก์ การยิงซ้ำ และการรันต่อ
    # เหตุผลที่ไม่ใช่ทั้งรอบอีกต่อไป: เกตเวย์ที่มีคนใช้ร่วมกันช้าไม่คงที่ ชุดใหญ่จึงถูกตัดสาย
    # ก่อนตอบเสร็จ แล้วเสียทั้งรอบทั้งที่ทำไปได้ตั้งเยอะ วัดเมื่อ 2026-09-21: ชุด 50 ตายที่
    # 29 นาที ชุด 5 ยังไม่จบใน 30 นาที ส่วนชุด 1 จบได้ที่ 586 วินาที
    done = set()
    if a.resume and os.path.exists(grades):
        with open(grades, encoding="utf-8") as f:
            done = {(json.loads(l)["round"], json.loads(l).get("chunk", 0)) for l in f if l.strip()}
        print(f"มีผลอยู่แล้ว {len(done)} ชุดย่อย จะข้ามไป")
    else:
        open(grades, "w").close()

    lock = threading.Lock()

    def run_chunk(r, c, shown):
        """ยิงชุดย่อยหนึ่งชุดจนสำเร็จหรือหมดสิทธิ์ยิงซ้ำ แล้วเขียนผลลงดิสก์ทันที"""
        prompt = build_prompt(ladder, shown)
        for attempt in range(1, a.tries + 1):
            t0 = time.time()
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
            dt = time.time() - t0
            with open(os.path.join(raw_dir, f"r{r}c{c}.txt"), "w", encoding="utf-8") as f:
                f.write(p.stdout)
            text, extra, err = p.stdout, {}, None
            try:
                payload = json.loads(p.stdout)
                text = payload.get("result", p.stdout)
                extra = {k: payload[k] for k in ("api", "temperature") if k in payload}
                err = payload.get("api_error_status")
            except ValueError:
                pass
            got = parse(text, size) if p.returncode == 0 else {}
            if got:
                pos = {it["n"]: i + 1 for i, it in enumerate(shown)}
                with lock, open(grades, "a", encoding="utf-8") as f:
                    for n, v in sorted(got.items()):
                        f.write(json.dumps(
                            {"round": r, "chunk": c, "n": n, "pos": pos[n],
                             "chunk_size": len(shown), "fit": v["fit"], "k": v["k"], "d": v["d"],
                             "secs": round(dt, 1), "tries": attempt,
                             "ladder_rev": rev, "prompt_rev": prompt_rev,
                             "reader": a.reader_id, "reader_cmd": a.reader,
                             **extra}, ensure_ascii=False) + "\n")
                return f"รอบ {r} ชุด {c}: ตอบมา {len(got)}/{len(shown)} · {dt:.0f} วิ · ยิง {attempt} ครั้ง"
            # 429 คือคิวเต็ม ซึ่งถูกปฏิเสธทันทีและยิงใหม่ได้เลย ต่างจากการถูกตัดสายที่เสียเวลาไปเปล่า ๆ
            # จึงรอสั้นเมื่อโดนปฏิเสธ และรอยาวขึ้นเรื่อย ๆ เมื่อเป็นอย่างอื่น
            busy = err == 429 or "429" in (p.stderr or "")
            wait = 5 if busy else min(60, 10 * 2 ** (attempt - 1))
            if attempt < a.tries:
                time.sleep(wait)
        return f"รอบ {r} ชุด {c}: ยิงครบ {a.tries} ครั้งแล้วยังไม่ได้คำตอบ — ข้ามไว้ก่อน"

    for r, order in enumerate(orders(size, a.order_seed), start=1):
        chunks = [(c, [items[i] for i in order[x:x + a.chunk]])
                  for c, x in enumerate(range(0, size, a.chunk), start=1)]
        todo = [(c, shown) for c, shown in chunks if (r, c) not in done]
        if not todo:
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.parallel) as pool:
            futs = [pool.submit(run_chunk, r, c, shown) for c, shown in todo]
            for fut in concurrent.futures.as_completed(futs):
                print(fut.result(), flush=True)

    print(f"เขียนแล้ว {grades} · ไม้บรรทัด rev {rev} · ตัวอ่าน {a.reader_id}")
    print(f"ต่อด้วย: python3 grading/score_gate1.py --out {a.out}")


if __name__ == "__main__":
    main()
