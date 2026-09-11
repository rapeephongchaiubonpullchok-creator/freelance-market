#!/usr/bin/env python3
"""ตัวเก็บสดของตลาดงาน Freelancer.com

วนลูปอยู่ในโปรเซสเดียว เพราะ `schedule:` ของ GitHub Actions ต่ำสุด 5 นาทีและถูกข้ามเมื่อโหลดสูง
ในหนึ่งรอบ (ค่าตั้งต้น 2 นาที) จะทำสิ่งที่ถูกที่สุดก่อน แล้วค่อยทำของแพงตามจังหวะของมันเอง:

  ทุกรอบ      ฟีดหน้าแรก (ค้นพบงานใหม่) + ยิงถามงานอายุน้อยกว่า 6 ชม.
  ทุก 2 ชม.   ยิงถามงานที่เปิดค้างทั้งหมด + กวาดช่วง ID ย้อนหลัง + ตามผลปลายทางที่ถึงกำหนด
  ทุก 6 ชม.   กวาดฟีดทีละหมวดทั้ง 17 หมวดจนถึงก้น

กำหนดเวลาของสองจังหวะช้าถูกจำลงไฟล์สถานะเป็นเวลานาฬิกาจริง ไม่ใช่นับจากตอนโปรเซสเริ่ม —
ไม่งั้น job ที่ถูกยามปลุกซ้ำถี่ ๆ จะเดินขาแพงทุกขาทันทีที่เริ่ม ทุกครั้งที่เริ่ม

เหตุผลของทุกจังหวะและตัวเลขที่วัดจริงอยู่ในโน้ตออกแบบซึ่งเก็บไว้ใน repo ส่วนตัว
อย่าปรับค่าเหล่านี้โดยไม่แก้โน้ตด้วย

ตัวอย่าง:
  python3 freelance-market/collect.py --data-dir .fmdata --once
  python3 freelance-market/collect.py --data-dir .fmdata --max-seconds 21000
"""
import argparse, json, os, re, signal, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmnet import Net, Blocked          # noqa: E402
from store import Store, StateMissing   # noqa: E402

HOUR = 3600
DAY = 86400
BIDS_RE = re.compile(r'"bids"\s*:\s*\[')
LOGO_RE = re.compile(r"/logo/(\d+)/")


def now():
    return int(time.time())


class Collector:
    def __init__(self, net, store, o):
        self.net, self.store, self.o = net, store, o
        self.state = store.load_state()
        self.state.setdefault("max_id", 0)
        self.state.setdefault("tracked", {})
        self.state.setdefault("done", {})
        self.state.setdefault("absent", {})
        # เวลานาฬิกาจริงของสองจังหวะช้า อยู่ในสถานะเพื่อให้ข้ามการรีสตาร์ตได้
        self.state.setdefault("next_slow", 0)
        self.state.setdefault("next_sweep", 0)
        self.cats = None
        self.users = {}                  # ชื่อผู้ใช้ -> ID ตัวเลข เก็บไว้ในหน่วยความจำรอบการรันนี้
        self.stop = False

    # ---------- การรับงานเข้าและการอ่านความเปลี่ยนแปลง ----------

    def ingest(self, projects, source, run):
        """งานที่ไม่เคยเห็น -> เขียนสายประกาศใหม่หนึ่งครั้ง · งานที่เคยเห็น -> อ่านส่วนต่าง"""
        for p in projects:
            pid = str(p.get("id"))
            if not pid or pid == "None":
                continue
            self.state["max_id"] = max(self.state["max_id"], int(pid))
            self.state["absent"].pop(pid, None)
            if pid in self.state["tracked"]:
                self.observe(p, run)
            elif pid in self.state["done"]:
                pass                     # ตามผลปลายทางจบไปแล้ว ไม่รับกลับเข้ามาอีก
            else:
                bs = p.get("bid_stats") or {}
                self.store.write("listings", {"id": p["id"], "src": source, "p": p})
                run["listings"] += 1
                self.state["tracked"][pid] = {
                    "t": p.get("time_submitted") or now(),
                    "n": bs.get("bid_count") or 0, "avg": bs.get("bid_avg"),
                    "seo": p.get("seo_url"), "st": p.get("status"),
                    "closed": 0, "page": 0, "due": [], "miss": 0}
                if p.get("status") != "active":
                    self.close(pid, p, run)

    def observe(self, p, run):
        pid = str(p["id"])
        e = self.state["tracked"][pid]
        e["miss"] = 0
        bs = p.get("bid_stats") or {}
        n2, avg2 = bs.get("bid_count") or 0, bs.get("bid_avg")
        n1, avg1 = e["n"], e["avg"]
        if n2 != n1 or (avg2 or 0) != (avg1 or 0):
            s1, s2 = (avg1 or 0) * n1, (avg2 or 0) * n2
            dn, dsum = n2 - n1, s2 - s1
            row = {"id": p["id"], "n": n2, "avg": avg2, "prev_n": n1, "prev_avg": avg1,
                   "d_n": dn, "d_sum": dsum}
            if dn == 0:
                # เข้าหนึ่งออกหนึ่ง: จำนวนนิ่งแต่ค่าเฉลี่ยขยับ ต้องนับไว้ว่าเกิดบ่อยแค่ไหน
                row["avg_moved_without_count"] = True
            elif dn < 0:
                row["withdrawn"] = -dn
            self.store.write("diffs", row)
            run["diffs"] += 1
            if dn == 1:
                # ช่วงที่มีบิดเข้ามาคนเดียว: ส่วนต่างคือราคาที่คนนั้นเสนอเป๊ะ ๆ
                self.store.write("bids", {"id": p["id"], "method": "exact",
                                          "amount": dsum, "n_from": n1, "n_to": n2})
                run["bids"] += 1
            elif dn > 1:
                self.store.write("bids", {"id": p["id"], "method": "group", "count": dn,
                                          "sum": dsum, "mean": dsum / dn,
                                          "n_from": n1, "n_to": n2})
                run["bids"] += 1
            e["n"], e["avg"] = n2, avg2
        if p.get("seo_url"):
            e["seo"] = p["seo_url"]
        if p.get("status") != "active" and not e["closed"]:
            self.close(pid, p, run)

    def close(self, pid, p, run):
        """แถวปิดท้ายของงาน — ข้อมูลที่มีค่าที่สุดในชุด เพราะบอกว่ามีคนได้งานหรือไม่"""
        e = self.state["tracked"][pid]
        e["closed"] = now()
        e["st"], e["sub"] = p.get("status"), p.get("sub_status")
        e["due"] = [now() + DAY, now() + 7 * DAY]
        self.store.write("outcomes", {
            "id": int(pid), "event": "closed", "status": p.get("status"),
            "sub_status": p.get("sub_status"), "n": e["n"], "avg": e["avg"],
            "age_h": round((now() - (e["t"] or now())) / HOUR, 2)})
        run["outcomes"] += 1

    # ---------- ขาเก็บแต่ละขา ----------

    def poll(self, ids, run, details=False):
        ids = [int(i) for i in ids]
        if not ids:
            return
        got = self.net.by_ids(ids, details=details)
        seen = set()
        for p in got:
            seen.add(int(p["id"]))
            if str(p["id"]) in self.state["tracked"]:
                self.observe(p, run)
            else:
                self.ingest([p], "id-query", run)
        for i in ids:
            if i in seen:
                continue
            e = self.state["tracked"].get(str(i))
            if e is None:
                continue
            e["miss"] = e.get("miss", 0) + 1
            if e["miss"] >= 3 and not e["closed"]:
                # หายจาก endpoint ไปสามรอบ = หายจริง ไม่ใช่จังหวะพลาด แต่ไม่รู้ว่าปิดแบบไหน
                self.close(str(i), {"status": "gone", "sub_status": None}, run)
                run["gone"] += 1

    def discover(self, run):
        ps = self.net.feed(limit=100)
        before = len(self.state["tracked"])
        self.ingest(ps, "feed", run)
        run["feed_seen"] = len(ps)
        run["feed_new"] = len(self.state["tracked"]) - before

    def sweep_categories(self, run):
        """กวาดทีละหมวด — ได้งานมากกว่าฟีดรวม 14.5% และไม่มีหมวดไหนชนเพดาน offset"""
        if self.cats is None:
            self.cats = self.net.categories() or {}
        pages = 0
        for cid in sorted(self.cats):
            prev = None
            for off in range(0, 5000, 100):
                ps = self.net.feed(limit=100, offset=off, category=cid)
                pages += 1
                ids = {p.get("id") for p in ps}
                # หน้ากลาง ๆ คืน 99 งานได้ตามปกติ จำนวนที่ไม่เต็มหน้าจึงไม่ใช่สัญญาณจบ
                # และ offset เกินเพดานไม่ error แต่คืนหน้าเดิมซ้ำเงียบ ๆ — หยุดที่หน้าว่างหรือหน้าซ้ำเท่านั้น
                if not ids or ids == prev:
                    break
                self.ingest(ps, f"cat{cid}", run)
                prev = ids
        run["sweep_pages"] = pages
        run["sweep_categories"] = len(self.cats)

    def sweep_ids(self, run):
        """กวาดช่วง ID ย้อนหลัง เพราะ ID เรียงตามเวลาแบบหลวม ๆ — เดินหน้าอย่างเดียวจะพลาดยับ"""
        hi = self.state["max_id"]
        if not hi:
            return
        lo = hi - self.o.id_back
        # ID ถูกจองตอนเริ่มร่าง ไม่ใช่ตอนประกาศ — งานโผล่ช้ากว่าเพื่อนบ้านได้ถึง 24 ชม.
        # ID ที่เคยไม่เจอจึงต้องถูกถามซ้ำจนครบ 24 ชม. ทั้งที่ยังอยู่ในหน้าต่างและที่หลุดออกไปแล้ว
        retry_cut = now() - DAY
        absent = self.state["absent"]
        ask = []
        for i in range(lo, hi + 1):
            k = str(i)
            if k in self.state["tracked"] or k in self.state["done"]:
                continue
            if k not in absent or absent[k] >= retry_cut:
                ask.append(i)
        ask += [int(k) for k, first in absent.items()
                if first >= retry_cut and not (lo <= int(k) <= hi)]
        if not ask:
            run["id_sweep"] = {"lo": lo, "hi": hi, "asked": 0, "found": 0, "absent": 0}
            return
        got = self.net.by_ids(ask, details=True)
        found = {int(p["id"]) for p in got}
        self.ingest(got, "id-sweep", run)
        missing = [i for i in ask if i not in found]
        fresh = [i for i in missing if str(i) not in absent]
        for i in missing:
            absent.setdefault(str(i), now())
        # ช่องว่างที่กวาดแล้วไม่เจอ ต้องถูกบันทึก ไม่ใช่ปล่อยผ่าน — ราวครึ่งของ ID ไม่ใช่งานสาธารณะ
        # เก็บเฉพาะ ID ที่เพิ่งพบว่าหาย ส่วนที่ถามซ้ำอยู่แล้วนับเป็นตัวเลข ไม่งั้นรายชื่อเดิมจะซ้ำทุกรอบตลอด 24 ชม.
        run["id_sweep"] = {"lo": lo, "hi": hi, "asked": len(ask), "found": len(found),
                           "absent": len(missing), "absent_retried": len(missing) - len(fresh),
                           "absent_ids": fresh}

    def outcomes_due(self, run):
        due = [pid for pid, e in self.state["tracked"].items()
               if e["due"] and e["due"][0] <= now()]
        if not due:
            return
        got = {int(p["id"]): p for p in self.net.by_ids([int(x) for x in due])}
        for pid in due:
            e = self.state["tracked"][pid]
            p = got.get(int(pid))
            stage = "+24h" if len(e["due"]) == 2 else "+7d"
            self.store.write("outcomes", {
                "id": int(pid), "event": "recheck" + stage,
                "status": (p or {}).get("status") if p else "gone",
                "sub_status": (p or {}).get("sub_status") if p else None,
                "n": ((p or {}).get("bid_stats") or {}).get("bid_count"),
                "avg": ((p or {}).get("bid_stats") or {}).get("bid_avg")})
            run["outcomes"] += 1
            e["due"].pop(0)
            if not e["due"]:
                self.state["done"][pid] = 1
                self.state["tracked"].pop(pid, None)

    # ---------- หน้าเว็บ ----------

    def carve_bids(self, html):
        """ดึงอาร์เรย์บิดที่ฝังในหน้า — ถอดด้วยตัวถอด JSON จริง เพราะข้อความเสนองานมีวงเล็บได้"""
        best = None
        dec = json.JSONDecoder()
        for m in BIDS_RE.finditer(html):
            i = m.end() - 1
            try:
                arr, _ = dec.raw_decode(html, i)
            except ValueError:
                continue
            if isinstance(arr, list) and (best is None or len(arr) > len(best)):
                best = arr
        return best

    def resolve_users(self, bids):
        """เก็บ ID ตัวเลขเท่านั้น ไม่เก็บชื่อผู้ใช้ — ID อ่านจาก URL รูปโปรไฟล์ได้ฟรีเป็นส่วนใหญ่"""
        need = []
        for b in bids:
            u = b.get("username")
            if not u or u in self.users:
                continue
            m = LOGO_RE.search(b.get("profileLogoUrl") or "")
            if m:
                self.users[u] = int(m.group(1))
            else:
                need.append(u)
        if need:
            self.users.update(self.net.user_ids(need))

    def fetch_pages(self, run):
        """ดึงหน้าเว็บงานละครั้งเดียวตอนงานปิดแล้ว — หน้าของงานที่ยังเปิดให้ค่ามั่ว"""
        todo = [pid for pid, e in self.state["tracked"].items()
                if e["closed"] and not e["page"] and e.get("seo")][:self.o.pages_per_cycle]
        for pid in todo:
            e = self.state["tracked"][pid]
            html = self.net.page(e["seo"])
            e["page"] = 1                                  # ยิงครั้งเดียวไม่ว่าจะได้อะไรกลับมา
            if html is None:
                self.store.write("pages", {"id": int(pid), "ok": 0, "reason": "http"})
                continue
            bids = self.carve_bids(html)
            if bids is None:
                self.store.write("pages", {"id": int(pid), "ok": 0, "reason": "no-block"})
                continue
            self.resolve_users(bids)
            rows, vis_sum, reviews = [], 0.0, []
            for b in bids:
                amt = b.get("amount")
                r = b.get("sellerRating") or {}
                if isinstance(amt, (int, float)):
                    vis_sum += amt
                reviews.append(r.get("reviewCount"))
                rows.append({"uid": self.users.get(b.get("username")), "amount": amt,
                             "period": b.get("period"), "desc": b.get("description"),
                             "rating": r.get("average"), "reviews": r.get("reviewCount"),
                             "completed": b.get("completed"),
                             "earn_pct": b.get("userEarningsPercentage"),
                             "addr": b.get("address")})
            n, avg = e["n"], e["avg"] or 0
            api_sum = n * avg
            unseen = n - len(rows)
            self.store.write("pages", {
                "id": int(pid), "ok": 1, "api_n": n, "api_avg": e["avg"],
                "page_n": len(rows), "visible_sum": vis_sum,
                # เกณฑ์ความครบคือผลรวม ไม่ใช่จำนวน — มีงานที่โชว์ 6 จาก 6 แต่ผลรวมขาด 12%
                "sum_matches": bool(unseen == 0 and abs(api_sum - vis_sum) < 0.01),
                "visible_mean": (vis_sum / len(rows)) if rows else None,
                # สองตัวเลขคาลิเบรต: อคติด้านราคา และความแรงของตัวกรองประสบการณ์
                "unseen_mean": ((api_sum - vis_sum) / unseen) if unseen > 0 else None,
                "min_reviews_visible": min([x for x in reviews if x is not None], default=None),
                "fraction_visible": (len(rows) / n) if n else None,
                "bids": rows})
            run["pages"] += 1

    # ---------- รอบการทำงาน ----------

    def prune(self):
        # ID เดินขึ้นราว 1,200 ตัว/วัน — 60,000 คือราว 50 วัน กว้างพอสำหรับงานที่เปิดค้างหลายวัน
        # แล้วยังต้องตามผลปลายทางต่ออีก 7 วัน ส่วน absent ถูกถามซ้ำแค่ 24 ชม. จึงตัดสั้นกว่ามาก
        cut_done = self.state["max_id"] - 60000
        cut_absent = now() - 2 * DAY
        self.state["done"] = {k: v for k, v in self.state["done"].items() if int(k) >= cut_done}
        self.state["absent"] = {k: v for k, v in self.state["absent"].items() if v >= cut_absent}

    def tick(self, tick_no):
        t0 = time.time()
        self.net.reset_counters()
        run = {"tick": tick_no, "listings": 0, "diffs": 0, "bids": 0,
               "outcomes": 0, "pages": 0, "gone": 0, "phases": []}
        try:
            run["phases"].append("discover")
            self.discover(run)

            cutoff = now() - self.o.fresh_hours * HOUR
            fresh = [pid for pid, e in self.state["tracked"].items()
                     if not e["closed"] and (e["t"] or 0) >= cutoff]
            run["fresh"] = len(fresh)
            run["phases"].append("poll-fresh")
            self.poll(fresh, run)

            if now() >= self.state["next_slow"]:
                self.state["next_slow"] = now() + self.o.slow
                run["phases"].append("poll-all")
                openp = [pid for pid, e in self.state["tracked"].items() if not e["closed"]]
                run["open"] = len(openp)
                self.poll(openp, run)
                run["phases"].append("id-sweep")
                self.sweep_ids(run)
                run["phases"].append("outcomes")
                self.outcomes_due(run)
                run["phases"].append("pages")
                self.fetch_pages(run)
                self.prune()

            if now() >= self.state["next_sweep"]:
                self.state["next_sweep"] = now() + self.o.sweep
                run["phases"].append("sweep-categories")
                self.sweep_categories(run)
        except Blocked as e:
            run["blocked"] = str(e)
        except Exception as e:                     # รอบเดียวพังต้องไม่ทำให้ตัวเก็บตายทั้งตัว
            run["error"] = f"{type(e).__name__}: {e}"

        run["tracked"] = len(self.state["tracked"])
        run["tracked_open"] = sum(1 for e in self.state["tracked"].values() if not e["closed"])
        run["done"] = len(self.state["done"])
        run["net"] = self.net.counters()
        run["secs"] = round(time.time() - t0, 2)
        # บันทึกการรันต้องมีทุกรอบไม่มีข้อยกเว้น — ไม่มีแถว = ไม่มีอะไรเปลี่ยน จะจริงก็ต่อเมื่อรู้ว่ารันสำเร็จ
        self.store.write("runs", run)
        self.store.flush()
        self.store.save_state(self.state)
        return run

    def loop(self):
        t_end = time.time() + self.o.max_seconds if self.o.max_seconds else None
        i = 0
        while not self.stop:
            i += 1
            r = self.tick(i)
            print(f"[{time.strftime('%H:%M:%S')}] รอบ {i} {r['secs']}s "
                  f"ยิง {r['net']['requests']} ประกาศใหม่ {r['listings']} ส่วนต่าง {r['diffs']} "
                  f"บิด {r['bids']} ปลายทาง {r['outcomes']} หน้าเว็บ {r['pages']} "
                  f"ติดตาม {r['tracked_open']}/{r['tracked']}"
                  + (f" [{r['error']}]" if r.get("error") else "")
                  + (f" [ถูกบล็อก {r['blocked']}]" if r.get("blocked") else ""), flush=True)
            if self.o.once:
                break
            if r.get("blocked"):
                time.sleep(600)
            if t_end and time.time() >= t_end:
                break
            time.sleep(max(0, self.o.tick - r["secs"]))
        self.store.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True,
                    help="ที่เก็บข้อมูล ต้องอยู่นอก git ของ repo นี้")
    ap.add_argument("--tick", type=float, default=120, help="วินาทีต่อรอบ (ค่าตั้งต้น 120)")
    ap.add_argument("--slow", type=float, default=2 * HOUR, help="จังหวะยิงงานเปิดค้างทั้งหมด")
    ap.add_argument("--sweep", type=float, default=6 * HOUR, help="จังหวะกวาดทีละหมวด")
    ap.add_argument("--fresh-hours", type=float, default=6, help="นิยามของ 'งานอายุน้อย'")
    ap.add_argument("--id-back", type=int, default=600, help="จำนวน ID ที่ถอยกลับทุกครั้งที่กวาด")
    ap.add_argument("--pages-per-cycle", type=int, default=40)
    ap.add_argument("--min-interval", type=float, default=0.4, help="วินาทีขั้นต่ำระหว่างรีเควสต์")
    ap.add_argument("--max-seconds", type=float, default=0, help="อายุของ job (0 = ไม่จำกัด)")
    ap.add_argument("--once", action="store_true", help="รันรอบเดียวแล้วออก ใช้ตอนทดสอบ")
    ap.add_argument("--verbose", action="store_true")
    o = ap.parse_args()

    net = Net(min_interval=o.min_interval, verbose=o.verbose)
    store = Store(o.data_dir)
    try:
        c = Collector(net, store, o)
    except StateMissing as e:
        # จบด้วยรหัสผิดพลาดแล้วรอคน ดีกว่าเริ่มนับหนึ่งใหม่เงียบ ๆ
        print(f"ตัวเก็บไม่เริ่ม: {e}", file=sys.stderr)
        return 2
    if o.once:
        c.state["next_slow"] = c.state["next_sweep"] = 0   # รอบทดสอบต้องเดินครบทุกขา
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: setattr(c, "stop", True))
    c.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
