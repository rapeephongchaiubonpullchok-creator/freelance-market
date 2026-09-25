#!/usr/bin/env python3
"""ที่เก็บของตัวเก็บ — ไฟล์ `.jsonl.gz` รายวันหกสาย บวกสถานะหนึ่งไฟล์

ไฟล์รายวันถูกต่อท้ายระหว่างวัน แล้วไม่ถูกแตะอีกเลยเมื่อวันผ่านไป — ขนาด repo
จึงเท่ากับขนาดข้อมูลพอดี ต่างจากไฟล์ที่ถูกเขียนทับทุกวันซึ่ง git จะเก็บสำเนาเต็มทุกเวอร์ชัน
สถานะเป็นข้อยกเว้นเดียวที่ถูกเขียนทับ เพราะมันคือ "เรารู้อะไรอยู่ตอนนี้" ไม่ใช่ข้อมูลที่เก็บได้
"""
import glob, gzip, json, os, time, zlib

STREAMS = ("listings", "diffs", "bids", "outcomes", "pages", "runs")


# --- ตัวอ่าน: ทุกตัวที่อ่านสายข้อมูลต้องผ่านสองฟังก์ชันนี้ ห้ามเปิด gzip เองที่อื่น ---
#
# ไฟล์ของ *วันปัจจุบัน* ไม่มีท้ายสตรีมเสมอ เพราะ `write()` ต่อท้ายแล้ว `flush()` ซึ่ง
# sync-flush ให้อ่านได้ทุกไบต์ แต่ CRC กับขนาดถูกเขียนตอน `close()` เท่านั้น คือตอน job
# หมดอายุหรือตอน `_rotate()` ข้ามเที่ยงคืน UTC ตัวอ่านจึงโยน `EOFError` หลังอ่านครบทุกแถว
# แล้ว — ข้อมูลไม่ได้หายและไม่ได้เสีย การรันกับข้อมูลสดจึงเจอแบบนี้ *ทุกครั้ง* ไม่ใช่กรณีพิเศษ

def read_rows(path, damage=None):
    """อ่านทีละบรรทัด ทนไฟล์ที่ยังไม่ถูกปิดหรือถูกตัดกลางคัน คืนเท่าที่อ่านได้"""
    rows = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    if damage is not None:
                        damage.append(f"{path}: บรรทัดเสีย 1 บรรทัด")
    except (EOFError, OSError, zlib.error) as e:
        if damage is not None:
            damage.append(
                f"{path}: อ่านไม่จบ ({type(e).__name__}) ใช้เท่าที่อ่านได้ {len(rows)} แถว")
    return rows


def read_stream(root, stream, damage=None):
    """ทุกแถวของสายหนึ่งจากทุกวัน เรียงตามเวลา"""
    assert stream in STREAMS, stream
    rows = []
    for p in sorted(glob.glob(os.path.join(root, "*", stream + ".jsonl.gz"))):
        rows.extend(read_rows(p, damage))
    return sorted(rows, key=lambda r: r.get("t", 0))


class StateMissing(Exception):
    """ไฟล์สถานะหาย ทั้งที่สายข้อมูลมีร่องรอยว่าเคยเก็บที่นี่มาก่อน"""


class StateStale(Exception):
    """ไฟล์สถานะเก่ากว่าสายข้อมูล — มีรอบที่เดินไปแล้วแต่สถานะของมันไม่ได้กลับมาด้วย"""

    def __init__(self, saved_t, last_run_t):
        self.saved_t, self.last_run_t = saved_t, last_run_t
        hm = lambda t: time.strftime("%m-%d %H:%M UTC", time.gmtime(t))   # noqa: E731
        super().__init__(f"สถานะบันทึกล่าสุด {hm(saved_t)} แต่บันทึกการรันล่าสุด {hm(last_run_t)} "
                         f"— ล้าไป {(last_run_t - saved_t) / 3600:.1f} ชม.")


# ช่วงที่ยอมให้สถานะช้ากว่าบันทึกการรัน: แต่ละรอบเขียนบันทึกก่อนแล้วค่อยเขียนสถานะ ถูกฆ่าตรงกลาง
# จึงช้าได้หนึ่งรอบโดยไม่มีอะไรผิด เกินห้ารอบแปลว่าสถานะมาจาก job ก่อนหน้า
STALE_AFTER = 600


class Store:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._day = None
        self._fh = {}

    def _rotate(self, day):
        for f in self._fh.values():
            f.close()
        self._fh = {}
        self._day = day
        os.makedirs(os.path.join(self.root, day), exist_ok=True)

    def write(self, stream, row):
        assert stream in STREAMS, stream
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if day != self._day:
            self._rotate(day)
        f = self._fh.get(stream)
        if f is None:
            f = self._fh[stream] = gzip.open(
                os.path.join(self.root, day, stream + ".jsonl.gz"), "at", encoding="utf-8")
        row.setdefault("t", int(time.time()))
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def flush(self):
        for f in self._fh.values():
            f.flush()

    def close(self):
        for f in self._fh.values():
            f.close()
        self._fh = {}

    # --- สถานะ ---

    def state_path(self):
        return os.path.join(self.root, "state.json.gz")

    def has_rows(self):
        """เคยเก็บลงที่เก็บนี้มาก่อนไหม — ไฟล์รายวันสายไหนก็นับ"""
        for d in sorted(os.listdir(self.root)):
            p = os.path.join(self.root, d)
            if not os.path.isdir(p):
                continue
            for stream in STREAMS:
                if os.path.exists(os.path.join(p, stream + ".jsonl.gz")):
                    return True
        return False

    def last_run_t(self):
        """เวลาของบันทึกการรันแถวล่าสุดในที่เก็บ — None ถ้ายังไม่มี"""
        for d in sorted(os.listdir(self.root), reverse=True):
            p = os.path.join(self.root, d, "runs.jsonl.gz")
            if os.path.exists(p):
                ts = [r.get("t") or 0 for r in read_rows(p)]
                if ts:
                    return max(ts)
        return None

    def load_state(self):
        """สถานะหายพร้อมกับที่เก็บว่างเปล่า = เริ่มต้นใหม่ · หายทั้งที่มีข้อมูลอยู่ = ต้องรอคน

        อย่างหลังคือทางเดียวที่ข้อมูลจะหายแบบไม่มีร่องรอย: ตัวเก็บจะนับ ID หนึ่งใหม่
        ทิ้งงานที่ยังตามผลปลายทางค้างอยู่ทั้งกอง แล้วเดินต่อเหมือนไม่มีอะไรเกิดขึ้น

        สถานะที่มีอยู่แต่เก่ากว่าบันทึกการรัน (push สถานะตอนจบ job ล้มแต่ push ข้อมูลผ่าน)
        โยน `StateStale` — ถ้าเดินต่อจากมัน งานที่เห็นไปแล้วในช่วงที่ขาดจะถูกบันทึกซ้ำทุกสาย
        สถานะรุ่นเก่าที่ยังไม่มี `saved_t` ตรวจไม่ได้ จึงปล่อยผ่าน
        """
        p = self.state_path()
        if not os.path.exists(p):
            if self.has_rows():
                raise StateMissing(
                    f"ไม่พบ {p} แต่ {self.root} มีไฟล์รายวันอยู่แล้ว — "
                    "ถ้าเริ่มใหม่ตรงนี้ งานที่ติดตามค้างอยู่จะหายเงียบทั้งหมด "
                    "ให้สร้างสถานะกลับจากสายข้อมูล หรือย้ายที่เก็บเดิมออกไปก่อนถ้าตั้งใจเริ่มใหม่จริง")
            return {"version": 1, "max_id": 0, "tracked": {}, "done": {}, "absent": {}}
        with gzip.open(p, "rt", encoding="utf-8") as f:
            state = json.load(f)
        saved, last = state.get("saved_t"), self.last_run_t()
        if saved and last and last - saved > STALE_AFTER:
            raise StateStale(saved, last)
        return state

    def save_state(self, state):
        """เขียนลงไฟล์ชั่วคราวแล้วค่อยสลับชื่อ — ถูกฆ่ากลางคันแล้วสถานะเดิมต้องยังอ่านได้"""
        p = self.state_path()
        tmp = p + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
