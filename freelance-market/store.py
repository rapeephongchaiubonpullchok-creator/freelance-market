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

    def load_state(self):
        """สถานะหายพร้อมกับที่เก็บว่างเปล่า = เริ่มต้นใหม่ · หายทั้งที่มีข้อมูลอยู่ = ต้องรอคน

        อย่างหลังคือทางเดียวที่ข้อมูลจะหายแบบไม่มีร่องรอย: ตัวเก็บจะนับ ID หนึ่งใหม่
        ทิ้งงานที่ยังตามผลปลายทางค้างอยู่ทั้งกอง แล้วเดินต่อเหมือนไม่มีอะไรเกิดขึ้น
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
            return json.load(f)

    def save_state(self, state):
        """เขียนลงไฟล์ชั่วคราวแล้วค่อยสลับชื่อ — ถูกฆ่ากลางคันแล้วสถานะเดิมต้องยังอ่านได้"""
        p = self.state_path()
        tmp = p + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
