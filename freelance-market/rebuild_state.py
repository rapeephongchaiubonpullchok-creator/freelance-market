#!/usr/bin/env python3
"""สร้างไฟล์สถานะกลับมาจากสายข้อมูล — ทางกู้ทางเดียวเมื่อสถานะหาย

ตัวเก็บจบด้วยรหัสผิดพลาดเมื่อหาสถานะไม่เจอทั้งที่ที่เก็บมีไฟล์รายวันอยู่ (ดู `store.load_state`)
สคริปต์นี้คือสิ่งที่คนที่ถูกเรียกมาดูต้องใช้ต่อ มันอ่านสายประกาศ ส่วนต่าง ผลปลายทาง หน้าเว็บ
และบันทึกการรัน แล้วเล่นเหตุการณ์ทั้งหมดซ้ำตามเวลา เพื่อประกอบทุกฟิลด์ของสถานะกลับมา

ค่าตั้งต้นคือ **ไม่เขียนอะไรเลย** — พิมพ์ว่าประกอบได้อะไรบ้างแล้วออก เพราะสถานการณ์ที่เรียกใช้
มันคือสถานการณ์ที่อะไรบางอย่างพังไปแล้ว การเขียนทับต้องเป็นคำสั่งที่ตั้งใจพิมพ์

  python3 freelance-market/rebuild_state.py --data-dir .fmdata            # ดูเฉย ๆ
  python3 freelance-market/rebuild_state.py --data-dir .fmdata --compare  # เทียบกับของจริง
  python3 freelance-market/rebuild_state.py --data-dir .fmdata --write

สิ่งที่กู้ไม่ได้ และไม่ใช่ความผิดพลาด:
  `miss`  ตัวนับงานที่หายจาก endpoint ติดกัน เริ่มที่ 0 ใหม่ อย่างมากคืองานที่หายไปแล้วถูกยิงถามซ้ำอีกสามรอบ
  `seo`   ใช้ค่าจากตอนประกาศ ถ้าเว็บเปลี่ยน seo_url ทีหลัง การเปลี่ยนนั้นไม่ได้ถูกเก็บลงสายไหนเลย
  จังหวะช้า  `next_slow`/`next_sweep` ตั้งเป็น 0 คือให้เดินขาแพงทันทีที่เริ่ม ซึ่งถูกต้องหลังจากที่ขาดหายไป
"""
import argparse, gzip, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import Store, STREAMS, read_rows      # noqa: E402

DAY = 86400
# ลำดับภายในวินาทีเดียวกัน: ประกาศต้องมาก่อนส่วนต่างของมันเสมอ ส่วนบันทึกการรันปิดท้าย
RANK = {"listings": 0, "diffs": 1, "bids": 2, "pages": 3, "outcomes": 4, "runs": 5}


def load_all(root):
    """รวมทุกแถวจากทุกวันทุกสาย แล้วเรียงตามเวลา — สถานะคือผลของการเล่นซ้ำตามลำดับนี้"""
    events, damage, files = [], [], 0
    for day in sorted(os.listdir(root)):
        d = os.path.join(root, day)
        if not os.path.isdir(d):
            continue
        for stream in STREAMS:
            p = os.path.join(d, stream + ".jsonl.gz")
            if not os.path.exists(p):
                continue
            files += 1
            for row in read_rows(p, damage):
                events.append((row.get("t") or 0, RANK[stream], stream, row))
    events.sort(key=lambda e: (e[0], e[1]))
    return events, damage, files


def rebuild(root, now=None):
    now = now or int(time.time())
    events, damage, files = load_all(root)
    tracked, done, absent = {}, {}, {}
    max_id = 0
    counts = {s: 0 for s in STREAMS}

    for t, _, stream, row in events:
        counts[stream] += 1
        pid = str(row.get("id")) if row.get("id") is not None else None

        if stream == "listings":
            p = row.get("p") or {}
            max_id = max(max_id, int(pid))
            absent.pop(pid, None)
            if pid in done or pid in tracked:
                continue          # ตามผลปลายทางจบไปแล้ว หรือเห็นมาก่อนแล้ว — ตัวเก็บก็ไม่รับซ้ำ
            bs = p.get("bid_stats") or {}
            tracked[pid] = {"t": p.get("time_submitted") or t,
                            "n": bs.get("bid_count") or 0, "avg": bs.get("bid_avg"),
                            "seo": p.get("seo_url"), "st": p.get("status"),
                            "closed": 0, "page": 0, "due": [], "miss": 0}

        elif stream == "diffs":
            e = tracked.get(pid)
            if e is not None:     # ส่วนต่างคือแหล่งเดียวที่ n กับ avg ขยับ จึงกู้ได้เป๊ะ
                e["n"], e["avg"] = row.get("n") or 0, row.get("avg")

        elif stream == "pages":
            e = tracked.get(pid)
            if e is not None:
                e["page"] = 1     # ยิงครั้งเดียวไม่ว่าผลจะเป็นอะไร ok=0 ก็นับว่ายิงแล้ว

        elif stream == "outcomes":
            e = tracked.get(pid)
            if e is None:
                continue
            ev = row.get("event")
            if ev == "closed":
                e["closed"] = t
                e["st"], e["sub"] = row.get("status"), row.get("sub_status")
                e["due"] = [t + DAY, t + 7 * DAY]
            elif ev and ev.startswith("recheck"):
                if row.get("n") is not None:
                    e["n"] = row["n"]
                if row.get("avg") is not None:
                    e["avg"] = row["avg"]
                if e["due"]:
                    e["due"].pop(0)
                if not e["due"]:
                    done[pid] = 1
                    tracked.pop(pid, None)

        elif stream == "runs":
            sw = row.get("id_sweep") or {}
            max_id = max(max_id, int(sw.get("hi") or 0))
            # บันทึกการรันจดเฉพาะ ID ที่ "เพิ่งพบว่าหาย" เวลาของแถวจึงเป็นเวลาที่พบครั้งแรกพอดี
            for i in sw.get("absent_ids") or []:
                absent.setdefault(str(i), t)

    for k in list(absent):
        if k in tracked or k in done:
            absent.pop(k)
    # ตัดเท่ากับ prune() ของตัวเก็บ ไม่งั้นสถานะที่กู้มาจะใหญ่กว่าที่ตัวเก็บจะยอมถือไว้เอง
    done = {k: v for k, v in done.items() if int(k) >= max_id - 60000}
    absent = {k: v for k, v in absent.items() if v >= now - 2 * DAY}

    state = {"version": 1, "max_id": max_id, "tracked": tracked, "done": done,
             "absent": absent, "next_slow": 0, "next_sweep": 0}
    report = {"files": files, "events": len(events), "rows": counts, "damage": damage,
              "now": now,
              "tracked_open": sum(1 for e in tracked.values() if not e["closed"]),
              "awaiting_outcome": sum(1 for e in tracked.values() if e["due"])}
    return state, report


def compare(old, new, now):
    """เทียบทีละฟิลด์ — `miss` กับจังหวะช้ากู้ไม่ได้โดยตั้งใจ จึงไม่นับเป็นความต่าง

    `absent` ที่เลยกำหนดตัดของ `prune()` ไปแล้วก็ไม่นับด้วย เพราะตัวเก็บตัดกองนี้เฉพาะในรอบช้า
    สถานะจริงจึงถือของที่หมดอายุค้างไว้ได้ถึงสองชั่วโมง ส่วนการกู้ตัดทันทีตามกติกาเดียวกัน
    ทั้งคู่ถูก ต่างกันแค่จังหวะ — และ ID กลุ่มนั้นเลยหน้าต่างถามซ้ำ 24 ชม. ไปแล้วทั้งหมด
    """
    out = []
    for k in ("max_id",):
        if old.get(k) != new.get(k):
            out.append(f"{k}: เดิม {old.get(k)} · กู้ได้ {new.get(k)}")
    for k in ("tracked", "done", "absent"):
        a, b = set(old.get(k) or {}), set(new.get(k) or {})
        if k == "absent":     # เทียบด้วยเส้นตัดเส้นเดียวกับที่การกู้ใช้ ไม่งั้นแค่เวลาต่างกันไม่กี่นาที
            a = {x for x in a if old["absent"][x] >= now - 2 * DAY}
        if a - b:
            out.append(f"{k}: หายไป {len(a - b)} ตัว เช่น {sorted(a - b)[:5]}")
        if b - a:
            out.append(f"{k}: เกินมา {len(b - a)} ตัว เช่น {sorted(b - a)[:5]}")
    for pid in sorted(set(old.get("tracked") or {}) & set(new.get("tracked") or {})):
        a, b = old["tracked"][pid], new["tracked"][pid]
        for f in ("t", "n", "avg", "seo", "st", "closed", "page", "due"):
            if a.get(f) != b.get(f):
                out.append(f"tracked[{pid}].{f}: เดิม {a.get(f)!r} · กู้ได้ {b.get(f)!r}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--write", action="store_true", help="เขียนทับ state.json.gz จริง")
    ap.add_argument("--force", action="store_true", help="ยอมเขียนทับสถานะที่มีอยู่แล้ว")
    ap.add_argument("--compare", action="store_true",
                    help="เทียบกับสถานะที่มีอยู่แล้วแทนการเขียน ต่างกัน = ออกด้วยรหัส 1")
    o = ap.parse_args()

    store = Store(o.data_dir)
    state, rep = rebuild(o.data_dir)
    print(f"อ่าน {rep['files']} ไฟล์ {rep['events']} แถว: "
          + " ".join(f"{k} {v}" for k, v in rep["rows"].items()))
    print(f"ประกอบได้: ติดตาม {len(state['tracked'])} งาน "
          f"(ยังเปิด {rep['tracked_open']} · รอผลปลายทาง {rep['awaiting_outcome']}) · "
          f"จบแล้ว {len(state['done'])} · ID ที่ยังหา {len(state['absent'])} · "
          f"max_id {state['max_id']}")
    for d in rep["damage"]:
        print("  เตือน:", d, file=sys.stderr)
    if not state["max_id"]:
        print("ไม่มีอะไรให้ประกอบ — ที่เก็บนี้ไม่มีแถวที่ใช้ได้เลย", file=sys.stderr)
        return 1

    p = store.state_path()
    if o.compare:
        if not os.path.exists(p):
            print(f"ไม่มี {p} ให้เทียบ", file=sys.stderr)
            return 1
        with gzip.open(p, "rt", encoding="utf-8") as f:
            diffs = compare(json.load(f), state, rep["now"])
        if not diffs:
            print("ตรงกับสถานะที่มีอยู่ทุกฟิลด์ที่กู้ได้")
            return 0
        print(f"ต่างกัน {len(diffs)} จุด:")
        for d in diffs[:40]:
            print("  " + d)
        if len(diffs) > 40:
            print(f"  ... อีก {len(diffs) - 40} จุด")
        return 1

    if not o.write:
        print(f"ยังไม่เขียนอะไร — ใส่ --write เพื่อเขียนลง {p}")
        return 0
    if os.path.exists(p) and not o.force:
        print(f"{p} มีอยู่แล้ว ใส่ --force ถ้าตั้งใจเขียนทับ", file=sys.stderr)
        return 1
    if rep["damage"] and not o.force:
        # อ่านไฟล์ไม่จบแปลว่าสถานะที่ได้ไม่ครบ ต้องเป็นการตัดสินใจของคน ไม่ใช่บรรทัดเตือนที่เลื่อนผ่านไป
        print("มีไฟล์ที่อ่านไม่จบ (ดูเตือนด้านบน) สถานะที่กู้ได้จึงไม่ครบ "
              "ใส่ --force ถ้ายอมรับ", file=sys.stderr)
        return 1
    store.save_state(state)
    print(f"เขียน {p} แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
