#!/usr/bin/env python3
"""รายงานภาพรวมตลาดจากข้อมูลที่ตัวเก็บสะสมไว้ — พิมพ์ในเทอร์มินัล ไม่ยิงเน็ต

เส้นแบ่งสองเส้นที่รายงานนี้ต้องไม่ข้าม และเป็นเหตุผลที่มันหน้าตาแบบนี้:

  ชุด ก / ชุด ข   งานที่โพสต์ *หลัง* ตัวเก็บเริ่มเดิน ครบจริงเพราะการกวาดช่วง ID
                  การันตี ส่วนงานเก่าที่บังเอิญยังเปิดค้างตอนกวาดรอบแรกคือ *กองที่
                  รอดมา* ไม่ใช่กองทั้งหมด — และที่หายไปคืองานที่ถูกจ้างแล้วพอดี
                  สองชุดเอียงคนละทาง **ห้ามบวกกัน** ทุกตารางจึงพิมพ์แยกเสมอ

  API / หน้าเว็บ  หัวข้อ 0–3 มาจาก API ครบทุกงานในหน้าต่างที่เก็บ พูดถึงได้ตรง ๆ
                  หัวข้อ 4 มาจากหน้าเว็บซึ่งโชว์บิดไม่ครบด้วยกฎที่ยังไม่รู้ ตัวเลข
                  ในนั้นคือ *คาลิเบรตของอคติ* ไม่ใช่ข้อค้นพบเรื่องตลาด และ
                  **ห้ามเอาไปเฉลี่ยข้ามงาน**

ความแออัดวัดที่ **อายุคงที่** (ตั้งต้น 24 ชม.) ไม่ใช่บิดดิบและไม่ใช่บิดหารอายุ —
บิดกระจุกช่วงต้น การหารด้วยอายุจึงพองงานใหม่และกดงานเก่าจนเทียบกันไม่ได้

  python3 freelance-market/report.py --data-dir <โคลนของ repo ข้อมูล>
"""
import argparse, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import read_stream      # noqa: E402

HOUR = 3600
# ฟีดบอกได้แค่ว่างานหายไป ซึ่งกลืนทุกกรณีเข้าด้วยกัน ป้ายที่แยกได้จริงมาจาก
# `projects/?projects[]=` และมีสองค่าที่แปลว่ามีคนได้งาน ไม่ใช่ค่าเดียว
AWARDED = ("closed_awarded", "frozen_awarded")
DAY = 86400
NOCAT = "(ไม่ระบุหมวด)"


# ---------- ตัวช่วยพิมพ์ ----------

def ts(t):
    return time.strftime("%m-%d %H:%M", time.gmtime(t))


def dur(s):
    s = int(s)
    if s < 90:
        return f"{s} วิ"
    if s < 5400:
        return f"{s / 60:.0f} นาที"
    if s < 2 * DAY:
        return f"{s / HOUR:.1f} ชม."
    return f"{s / DAY:.1f} วัน"


def quart(xs):
    """ควอไทล์ล่าง/กลาง/บน — คืน None เมื่อตัวอย่างน้อยเกินกว่าจะมีความหมาย"""
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 4:
        return None
    def at(f):
        i = f * (len(xs) - 1)
        lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
    return at(0.25), at(0.5), at(0.75)


def num(x, w=0, dp=0):
    return "—".rjust(w) if x is None else f"{x:,.{dp}f}".rjust(w)


def span3(q, w, dp=0):
    """ควอไทล์สามค่าในช่องเดียว — ชิดขวาเป็นก้อน ไม่ใช่สามคอลัมน์ที่ลอยจากกัน"""
    if q is None:
        return "ยังน้อยเกินไป".rjust(w)
    return f"{num(q[0], 0, dp)}–{num(q[1], 0, dp)}–{num(q[2], 0, dp)}".rjust(w)


def cut(s, w):
    s = s or ""
    return s if len(s) <= w else s[:w - 1] + "…"


def head(n, title):
    print()
    print("=" * 78)
    print(f"{n}. {title}")
    print("=" * 78)


# ---------- อ่านข้อมูล ----------

def build_jobs(listings, diffs):
    """หนึ่งแถวต่อหนึ่งงาน พร้อมเส้นเวลาของบิดที่ต่อจากประกาศแรกด้วยสายส่วนต่าง"""
    jobs = {}
    for r in listings:
        pid = r.get("id")
        p = r.get("p") or {}
        if pid is None or pid in jobs:
            continue
        cur, bud = p.get("currency") or {}, p.get("budget") or {}
        bs = p.get("bid_stats") or {}
        cats = sorted({(j.get("category") or {}).get("name")
                       for j in (p.get("jobs") or [])
                       if (j.get("category") or {}).get("name")})
        jobs[pid] = {
            "submit": p.get("time_submitted") or r.get("t"),
            "type": p.get("type"),
            # สถานะตอนเห็นครั้งแรก — งานที่ไม่ active ตั้งแต่แรกไม่เคยอยู่ในตลาดเปิด
            "st0": p.get("status"),
            "cats": cats or [NOCAT],
            "rate": cur.get("exchange_rate"),
            "bmin": bud.get("minimum"),
            "bmax": bud.get("maximum"),
            "obs": [(r.get("t"), bs.get("bid_count") or 0, bs.get("bid_avg"))],
        }
    for d in diffs:
        j = jobs.get(d.get("id"))
        if j is not None:
            j["obs"].append((d.get("t"), d.get("n") or 0, d.get("avg")))
    for j in jobs.values():
        j["obs"].sort(key=lambda x: x[0])
        j["n_last"], j["avg_last"] = j["obs"][-1][1], j["obs"][-1][2]
    return jobs


def build_outcomes(rows):
    """ยุบสายผลปลายทางให้เหลืองานละหนึ่ง — งานหนึ่งมีทั้งแถว closed และ recheck ได้

    บั๊กนับซ้ำที่เคยเกิดมาแล้ว: นับทั้งสองแถวจะได้อัตราถูกจ้างสูงเป็นสองเท่า
    ป้ายที่ใช้คือป้ายล่าสุดที่ไม่ว่าง เพราะ recheck ทีหลังเห็นสถานะที่นิ่งแล้ว
    """
    out = {}
    for r in rows:
        pid = r.get("id")
        if pid is None:
            continue
        e = out.setdefault(pid, {"sub": None, "status": None, "age_h": None})
        if r.get("event") == "closed" and r.get("age_h") is not None:
            e["age_h"] = r["age_h"]
        if r.get("sub_status"):
            e["sub"] = r["sub_status"]
        if r.get("status"):
            e["status"] = r["status"]
    return out


# ---------- หัวข้อ 0: ความครบของข้อมูล ----------

def section_coverage(runs, jobs, t0, t1, damage):
    head(0, "ความครบของข้อมูล — อ่านก่อนเชื่อตัวเลขข้อไหนก็ตาม")
    span = max(t1 - t0, 1)
    print(f"ช่วงที่มีข้อมูล  {ts(t0)}–{ts(t1)} UTC ({dur(span)} · {len(runs)} รอบ)")

    holes = [(a["t"], b["t"] - a["t"]) for a, b in zip(runs, runs[1:])
             if b["t"] - a["t"] > HOUR]
    lost = sum(d for _, d in holes)
    print(f"ช่องว่างที่ยาวเกิน 1 ชม.  {len(holes)} ช่อง รวม {dur(lost)} "
          f"= {100 * lost / span:.1f}% ของช่วง")
    for t, d in holes[:5]:
        print(f"    หลัง {ts(t)} เว้นไป {dur(d)}")
    if len(holes) > 5:
        print(f"    … อีก {len(holes) - 5} ช่อง")
    if holes:
        print("  ช่องว่างกินความละเอียดของบิดในช่วงนั้นไปถาวร — ตัวเลขความแออัดในหัวข้อ 3")
        print("  อ่านได้น้อยลงตามส่วน ถ้าอยากรู้ว่าขาดตรงไหนจริง ๆ ให้รัน gaps.py ต่อ")
    if damage:
        print("\nไฟล์ที่อ่านไม่จบ (ปกติสำหรับไฟล์ของวันปัจจุบัน ข้อมูลไม่ได้หาย):")
        for d in damage:
            print("   ", d)

    a = [j for j in jobs.values() if j["submit"] >= t0]
    b = [j for j in jobs.values() if j["submit"] < t0]
    print(f"\nงานทั้งหมดในที่เก็บ {len(jobs):,} งาน")
    print(f"  ชุด ก  {len(a):>6,} งาน  โพสต์หลังตัวเก็บเริ่มเดิน — ครบจริง "
          f"การกวาดช่วง ID การันตี")
    print(f"  ชุด ข  {len(b):>6,} งาน  โพสต์ก่อนหน้านั้น — *กองที่รอดมา* ไม่ใช่กองทั้งหมด")

    # เส้นเหลือรอดรายวัน: เทียบจำนวนงานเก่าที่ยังเปิดค้าง กับอัตราโพสต์จริงที่ชุด ก วัดได้
    per_day = [sum(1 for j in a if t0 + d * DAY <= j["submit"] < t0 + (d + 1) * DAY)
               for d in range(int(span // DAY))]
    base = sorted(per_day)[len(per_day) // 2] if per_day else 0
    print(f"\nเส้นเหลือรอดรายวัน — ฐานคืออัตราโพสต์จริงที่ชุด ก วัดได้ {base:,} งาน/วัน")
    if not base:
        print("  ยังเก็บไม่ครบหนึ่งวันเต็ม ยังวัดฐานไม่ได้")
        return a, b
    print(f"  ฐานนี้เป็นค่ากลางของวันเต็มเพียง {len(per_day)} วัน อัตราโพสต์ต่างกันตาม")
    print("  วันในสัปดาห์อยู่แล้ว เส้นข้างล่างจึงยังไม่ควรคาดว่าจะลดลงเรียบ ๆ")
    print(f"  {'ย้อนไป':>8} {'งานที่ยังเปิดค้าง':>18} {'เหลือรอด':>10}")
    for d in range(1, 8):
        lo, hi = t0 - d * DAY, t0 - (d - 1) * DAY
        k = sum(1 for j in b if lo <= j["submit"] < hi)
        print(f"  {d:>5} วัน {k:>18,} {100 * k / base:>9.0f}%")
    print("  ที่หายไปจากชุด ข ไม่ใช่การสุ่ม — มันคืองานที่ถูกจ้างแล้วหลุดจากฟีดไปก่อน")
    print("  เราเริ่มเก็บ ชุด ข จึงเอียงลงด้านอัตราถูกจ้างอย่างเป็นระบบ")
    return a, b


# ---------- หัวข้อ 1: งานแยกตามสายงาน ----------

def section_fields(a, b):
    head(1, "งานแยกตามสายงาน (API — ครบทุกงานในหน้าต่างที่เก็บ)")
    cats = sorted({c for j in a + b for c in j["cats"]})
    print("งานหนึ่งงานติดได้หลายหมวด ผลรวมของคอลัมน์จึงมากกว่าจำนวนงาน")
    print(f"\n  {'หมวด':<26} {'ชุด ก':>7} {'%':>6} {'เหมา/ชม.':>11}   "
          f"{'ชุด ข':>7} {'%':>6}")
    rows = []
    for c in cats:
        ja = [j for j in a if c in j["cats"]]
        jb = [j for j in b if c in j["cats"]]
        rows.append((len(ja), c, ja, jb))
    for n, c, ja, jb in sorted(rows, reverse=True):
        fx = sum(1 for j in ja if j["type"] == "fixed")
        hr = sum(1 for j in ja if j["type"] == "hourly")
        print(f"  {cut(c, 26):<26} {n:>7,} {100 * n / max(len(a), 1):>5.1f}% "
              f"{fx:>5,}/{hr:<5,} {len(jb):>7,} {100 * len(jb) / max(len(b), 1):>5.1f}%")


# ---------- หัวข้อ 2: ราคา ----------

def usd(x, rate):
    return None if (x is None or not rate) else x * rate


def price_table(jobs, kind, label):
    sel = [j for j in jobs if j["type"] == kind]
    drop = sum(1 for j in sel if not j["rate"])
    print(f"\n{label} — {len(sel):,} งาน" +
          (f" (ตัดออก {drop} งานที่ไม่มีอัตราแลกเปลี่ยน)" if drop else ""))
    if not sel:
        return
    cats = sorted({c for j in sel for c in j["cats"]})
    unit = "ทั้งโปรเจกต์" if kind == "fixed" else "ต่อชั่วโมง"
    print(f"  ทุกยอดเป็น USD {unit}")
    print(f"  {'หมวด':<24} {'งาน':>6}  {'ช่วงงบที่ลูกค้าตั้ง':>14}  "
          f"{'ราคาที่ฟรีแลนซ์เสนอ (ล่าง–กลาง–บน)':>22}")
    rows = sorted(((len([j for j in sel if c in j["cats"]]), c) for c in cats), reverse=True)
    for n, c in rows:
        js = [j for j in sel if c in j["cats"]]
        # ช่วงงบพิมพ์เป็น ค่ากลางของพื้น–ค่ากลางของเพดาน เพราะบิดมักเกาะเพดาน
        # ส่วนราคาที่เสนอพิมพ์เป็นควอไทล์ เพราะนั่นคือการกระจายที่ต้องแข่งด้วยจริง
        qlo = quart([usd(j["bmin"], j["rate"]) for j in js])
        qhi = quart([usd(j["bmax"], j["rate"]) for j in js])
        qa = quart([usd(j["avg_last"], j["rate"]) for j in js if j["n_last"]])
        band = "ยังน้อยเกินไป".rjust(14) if not (qlo and qhi) else \
            f"{num(qlo[1])}–{num(qhi[1])}".rjust(14)
        print(f"  {cut(c, 24):<24} {n:>6,}  {band}  {span3(qa, 22)}")


def section_price(a, b):
    head(2, "ราคา (API) — เหมาจ่ายกับรายชั่วโมงแยกถังเด็ดขาด")
    print("ค่ากลางของสองแบบนี้รวมกันไม่มีความหมายทางใดเลย และแปลงข้ามกันไม่ได้")
    print("เพราะข้อมูลไม่มีความยาวงานเป็นสัปดาห์ · แปลงเป็น USD ด้วยเรตของวันนี้")
    print("ซึ่งใช้ได้เพราะทุกงานในชุดนี้อายุไม่กี่วัน ไม่ใช่หลายปี")
    print("\n" + "-" * 78)
    print("ชุด ก — โพสต์หลังตัวเก็บเริ่มเดิน")
    price_table(a, "fixed", "เหมาจ่าย")
    price_table(a, "hourly", "รายชั่วโมง")
    print("\n" + "-" * 78)
    print("ชุด ข — งานเก่าที่ยังเปิดค้าง (กองที่รอดมา ห้ามเอาไปบวกกับชุด ก)")
    price_table(b, "fixed", "เหมาจ่าย")
    price_table(b, "hourly", "รายชั่วโมง")


# ---------- หัวข้อ 3: ความแออัดและผลปลายทาง ----------

def bids_at_age(j, age_s):
    """จำนวนบิดของงานนี้ตอนอายุครบ age_s — คืน None เมื่อเส้นเวลาตอบไม่ได้

    ตอบได้ต่อเมื่อเห็นงานตั้งแต่ก่อนถึงหมุดนั้น *และ* ยังเห็นมันหลังหมุดนั้นด้วย
    ไม่งั้นค่าที่ได้คือ "เท่าที่ทันเห็น" ซึ่งต่ำกว่าจริงโดยไม่รู้เท่าไหร่
    """
    mark = j["submit"] + age_s
    before = [n for t, n, _ in j["obs"] if t <= mark]
    after = any(t >= mark for t, _, _ in j["obs"])
    if not before or not after:
        return None
    return before[-1]


def section_crowding(jobs, a, b, outcomes, t0, t1, age_h):
    head(3, f"ความแออัดที่อายุคงที่ {age_h:g} ชม. และผลปลายทาง (API)")
    print("วัดที่อายุคงที่ ไม่ใช่บิดดิบและไม่ใช่บิดหารอายุ — บิดกระจุกช่วงต้น")
    print("การหารด้วยอายุจึงพองงานใหม่เป็นหลักร้อยบิด/วัน และกดงานอายุสัปดาห์ลง")
    print("ชุด ข วัดข้อนี้ไม่ได้เลย เพราะไม่มีประวัติ 24 ชม. แรกของมัน")

    age_s = age_h * HOUR
    ok, young, blind = [], 0, 0
    for j in a:
        if t1 - j["submit"] < age_s:
            young += 1
            continue
        n = bids_at_age(j, age_s)
        if n is None:
            blind += 1
            continue
        ok.append((j, n))

    print(f"\nงานในชุด ก ที่อายุถึง {age_h:g} ชม. แล้วและเส้นเวลาตอบได้  {len(ok):,} งาน")
    print(f"  ตัดออก: อายุยังไม่ถึง {young:,} งาน · เส้นเวลาขาดช่วงคร่อมหมุด {blind:,} งาน")
    if ok:
        cats = sorted({c for j, _ in ok for c in j["cats"]})
        label = f"บิดที่ {age_h:g} ชม. (ล่าง–กลาง–บน)"
        print(f"\n  {'หมวด':<26} {'งาน':>6}  {label:>28}")
        rows = sorted(((sum(1 for j, _ in ok if c in j["cats"]), c) for c in cats),
                      reverse=True)
        for n, c in rows:
            q = quart([v for j, v in ok if c in j["cats"]])
            print(f"  {cut(c, 26):<26} {n:>6,}  {span3(q, 28, 1)}")
        q = quart([v for _, v in ok])
        if q:
            print(f"  {'ทั้งตลาด':<26} {len(ok):>6,}  {span3(q, 28, 1)}")
    else:
        print("  ยังไม่มีงานที่วัดได้ — รอให้ตัวเก็บเดินต่ออีกหน่อย")

    # ---- ผลปลายทาง ----
    print("\n" + "-" * 78)
    print("ผลปลายทาง — พิมพ์เป็น *ขอบล่าง* ไม่ใช่อัตราถูกจ้าง")
    print("ชุด ก ถูกตัดปลาย งานที่จะหมดอายุต้องรอครบ bidperiod 7 วัน ตอนนี้จึงเห็น")
    print("แต่งานที่ถูกจ้างเร็ว ส่วนชุด ข เอียงลงจากการรอดมา ทั้งคู่ยังไม่ใช่อัตราจริง")
    # งานที่เห็นครั้งแรกก็ไม่ active แล้ว ต้องแยกออกจากทุกตัวเลขของหัวข้อนี้ — มัน
    # ไม่เคยอยู่ในตลาดเปิดให้ใครแย่ง เอาไปปนแล้วอายุตอนปิดจะถูกดึงลงเหลือหลักชั่วโมง
    # และอัตราถูกจ้างจะนับงานที่เราไม่เคยเห็นตอนมันเปิดรับบิดเลย
    for label, grp, total in (("ชุด ก", a, len(a)), ("ชุด ข", b, len(b))):
        live = {pid: outcomes[pid] for pid in outcomes
                if pid in jobs and jobs[pid] in grp and jobs[pid]["st0"] == "active"}
        doa = [pid for pid in outcomes
               if pid in jobs and jobs[pid] in grp and jobs[pid]["st0"] != "active"]
        if not live:
            continue
        counts = {}
        for e in live.values():
            k = e["sub"] or e["status"] or "(ไม่ทราบ)"
            counts[k] = counts.get(k, 0) + 1
        hired = sum(counts.get(k, 0) for k in AWARDED)
        base = total - len(doa)
        print(f"\n  {label} — เห็นตอนยังเปิดอยู่ {base:,} งาน · ปิดไปแล้ว {len(live):,} งาน")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {cut(k, 22):<22} {v:>7,} {100 * v / len(live):>6.1f}% ของงานที่ปิด")
        print(f"    จ้างแล้วอย่างน้อย {100 * hired / base:.1f}% ของทั้งชุด "
              f"({hired:,} งาน = closed_awarded + frozen_awarded)")
        if doa:
            print(f"    แยกไว้ต่างหาก: {len(doa):,} งานที่เห็นครั้งแรกก็ไม่ active แล้ว "
                  f"— ไม่เคยอยู่ในตลาดเปิด")

    # อายุตอนปิด: อ่านจากแถว `closed` เท่านั้น แถวถามซ้ำมีอายุบวกไปอีก 24 ชม.
    # ซึ่งเป็นกำหนดของเราเอง ไม่ใช่ของตลาด
    print("\n  อายุตอนปิด — เฉพาะงานที่เห็นตอนยังเปิดอยู่")
    print(f"  ชุด ก ถูกตัดปลายหนัก: หน้าต่างที่เก็บกว้าง {dur(t1 - t0)} งานที่จะปิด")
    print("  ตอนอายุ 7 วันยังปิดไม่ได้ในนี้ ตัวเลขของชุด ก จึงไม่ใช่การกระจายของตลาด")
    print(f"\n  {'ชุด':<8} {'งาน':>6} {'ควอไทล์ ล่าง–กลาง–บน (ชม.)':>30} "
          f"{'<24 ชม.':>9} {'24–160':>8} {'≥160':>7}")
    for label, grp in (("ชุด ก", a), ("ชุด ข", b)):
        ages = [e["age_h"] for pid, e in outcomes.items()
                if e["age_h"] is not None and pid in jobs
                and jobs[pid] in grp and jobs[pid]["st0"] == "active"]
        if not ages:
            continue
        fast = 100 * sum(1 for x in ages if x < 24) / len(ages)
        mid = 100 * sum(1 for x in ages if 24 <= x < 160) / len(ages)
        slow = 100 * sum(1 for x in ages if x >= 160) / len(ages)
        print(f"  {label:<8} {len(ages):>6,} {span3(quart(ages), 30, 1)} "
              f"{fast:>8.0f}% {mid:>7.0f}% {slow:>6.0f}%")
    print("\n  ยอดที่ ≥160 ชม. คือ bidperiod 7 วันหมดอายุพอดี ไม่ใช่การจ้าง — ที่ไหน")
    print("  มีทั้งสองยอด ค่ากลางเดี่ยวจะไม่อธิบายงานกลุ่มไหนเลย ต้องอ่านเป็นสองกลุ่ม")


# ---------- หัวข้อ 4: หน้าเว็บ ----------

def section_pages(pages):
    head(4, "ข้อมูลหน้าเว็บ — คาลิเบรตของอคติ ไม่ใช่ข้อค้นพบเรื่องตลาด")
    print("หน้าเว็บโชว์บิดไม่ครบด้วยกฎที่ยังไม่รู้ และเป็นคุณสมบัติคงที่ของงาน")
    print("ตัวเลขในหัวข้อนี้ **ห้ามเอาไปเฉลี่ยข้ามงาน** และห้ามใช้ตอบคำถามเรื่องราคา")
    print("ข้ามงาน ทุกตัวเลขข้างล่างเป็นการเทียบ *ภายในงานเดียวกัน* แล้วค่อยดูการกระจาย")

    ok = [p for p in pages if p.get("ok")]
    bad = {}
    for p in pages:
        if not p.get("ok"):
            bad[p.get("reason") or "(ไม่ระบุ)"] = bad.get(p.get("reason") or "(ไม่ระบุ)", 0) + 1
    print(f"\nดึงหน้าเว็บไปแล้ว {len(pages):,} งาน · สำเร็จ {len(ok):,} งาน")
    for k, v in sorted(bad.items(), key=lambda x: -x[1]):
        print(f"    ล้มเหลว {k:<12} {v:>6,}")
    if not ok:
        return

    q = quart([p.get("fraction_visible") for p in ok])
    if q:
        print(f"\nสัดส่วนบิดที่หน้าเว็บโชว์  กลาง {100 * q[1]:.1f}% "
              f"(ควอไทล์ {100 * q[0]:.1f}–{100 * q[2]:.1f}%)")
    match = sum(1 for p in ok if p.get("sum_matches"))
    print(f"จับคู่บิดคนต่อคนกับ API ได้  {match:,} งาน = "
          f"{100 * match / len(ok):.1f}% ของงานที่ดึงสำเร็จ")
    print("  เกณฑ์คือผลรวมยอดบิดต้องลงตัวพอดี ไม่ใช่จำนวนตรงกัน — มีงานที่โชว์ 6 จาก 6")
    print("  แต่ผลรวมขาด 12% คำถามที่ต้องรู้ว่า 'คนไหนเสนอเท่าไหร่' จึงมีฐานเท่าตัวเลขนี้")

    # อคติด้านราคา: เทียบกลุ่มที่เห็นกับกลุ่มที่ไม่เห็น *ภายในงานเดียวกัน* แล้วดูการกระจาย
    gaps = [100 * (p["unseen_mean"] - p["visible_mean"]) / p["visible_mean"]
            for p in ok
            if p.get("unseen_mean") and p.get("visible_mean")]
    print(f"\nอคติด้านราคา — กลุ่มที่ไม่เห็นแพงกว่ากลุ่มที่เห็นกี่ % ({len(gaps):,} งานที่วัดได้)")
    q = quart(gaps)
    if q is None:
        print("  ยังน้อยเกินกว่าจะดูการกระจาย")
    else:
        print(f"  ควอไทล์ล่าง {q[0]:+.1f}% · กลาง {q[1]:+.1f}% · ควอไทล์บน {q[2]:+.1f}%")
        near = sum(1 for g in gaps if abs(g) < 5)
        print(f"  งานที่สองกลุ่มต่างกันไม่ถึง 5% มี {100 * near / len(gaps):.0f}% "
              f"— ยิ่งราคาสองกลุ่มเหมือนกัน ยิ่งบอกจากราคาไม่ได้ว่าใครเป็นใคร")

    # ความแรงของตัวกรองประสบการณ์: รีวิวต่ำสุดที่เห็น เทียบกับสัดส่วนที่เห็น
    print("\nตัวกรองประสบการณ์ — รีวิวต่ำสุดในชุดที่เห็น แยกตามว่าเห็นมากน้อยแค่ไหน")
    print("  เมื่อเว็บต้องเลือก มันเลือกคนเก๋า เมื่อไม่ต้องเลือก มันโชว์ทุกคน")
    print(f"  {'สัดส่วนที่เห็น':<16} {'งาน':>6} {'รีวิวต่ำสุด (ล่าง–กลาง–บน)':>30} "
          f"{'ที่ยังเห็นมือใหม่':>18}")
    bands = [(0.0, 0.25, "ไม่ถึง 25%"), (0.25, 0.5, "25–50%"),
             (0.5, 0.9, "50–90%"), (0.9, 1.01, "90% ขึ้นไป")]
    for lo, hi, lab in bands:
        js = [p for p in ok if p.get("fraction_visible") is not None
              and lo <= p["fraction_visible"] < hi
              and p.get("min_reviews_visible") is not None]
        if not js:
            continue
        q = quart([p["min_reviews_visible"] for p in js])
        cell = "ยังน้อยเกินไป" if q is None else \
            f"{num(q[0], 8, 1)}–{num(q[1], 8, 1)}–{num(q[2], 8, 1)}"
        zero = sum(1 for p in js if p["min_reviews_visible"] == 0)
        print(f"  {lab:<16} {len(js):>6,} {cell:>30} "
              f"{100 * zero / len(js):>17.0f}%")
    print("\n  ตัวกรองนี้แรงขึ้นตามจำนวนคนแย่ง ถ้าเอาไปเฉลี่ยข้ามงานเป็น 'คนที่แข่ง")
    print("  หมวดนี้เก่งแค่ไหน' จะได้คำตอบสูงเกินจริงอย่างเป็นระบบ ใช้เทียบภายในงานเดียวกันเท่านั้น")


# ---------- ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--crowd-age-hours", type=float, default=24,
                    help="หมุดอายุคงที่ที่ใช้วัดความแออัด (ค่าตั้งต้น 24)")
    o = ap.parse_args()

    damage = []
    runs = read_stream(o.data_dir, "runs", damage)
    if not runs:
        print(f"ไม่พบสาย runs ใน {o.data_dir} — ที่เก็บนี้ยังไม่มีข้อมูล", file=sys.stderr)
        return 1
    listings = read_stream(o.data_dir, "listings", damage)
    diffs = read_stream(o.data_dir, "diffs", damage)
    outcomes = build_outcomes(read_stream(o.data_dir, "outcomes", damage))
    pages = read_stream(o.data_dir, "pages", damage)

    jobs = build_jobs(listings, diffs)
    t0, t1 = runs[0]["t"], runs[-1]["t"]

    a, b = section_coverage(runs, jobs, t0, t1, damage)
    section_fields(a, b)
    section_price(a, b)
    section_crowding(jobs, a, b, outcomes, t0, t1, o.crowd_age_hours)
    section_pages(pages)

    print()
    print("=" * 78)
    print("แนวโน้มข้ามเวลายังพูดไม่ได้ — ข้อมูลนี้ไม่มีอดีตก่อนวันที่ตัวเก็บเริ่มเดิน")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
