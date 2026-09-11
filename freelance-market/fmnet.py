#!/usr/bin/env python3
"""ชั้นเครือข่ายของตัวเก็บ — คุมจังหวะยิง ถอย และนับทุกอย่างที่ยิงออกไป

แยกออกมาเป็นไฟล์เดียวเพราะสองอย่าง: บันทึกการรันต้องรู้ว่ายิงไปกี่ครั้งและพังกี่ครั้ง
และการถูกจำกัดอัตราต้องถูกจับที่จุดเดียว ไม่ใช่กระจายอยู่ในทุกที่ที่เรียก
"""
import gzip, json, time, urllib.error, urllib.parse, urllib.request, zlib

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
API = "https://www.freelancer.com/api/projects/0.1"
USERS_API = "https://www.freelancer.com/api/users/0.1"
WEB = "https://www.freelancer.com"


class Blocked(Exception):
    """ยิงพลาดติดกันจนน่าเชื่อว่าถูกบล็อก ไม่ใช่เน็ตสะดุด — ผู้เรียกต้องหยุดรอบนี้"""


class Net:
    def __init__(self, min_interval=0.4, timeout=45, retries=3, block_after=8, verbose=False):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.block_after = block_after
        self.verbose = verbose
        self._last = 0.0
        self.streak = 0          # จำนวนครั้งที่พลาดติดกัน
        self.reset_counters()

    def reset_counters(self):
        self.n_req = 0
        self.n_bytes = 0
        self.n_retry = 0
        self.n_fail = 0
        self.t_sum = 0.0         # วินาทีที่ใช้ยิงจริง ไม่รวมเวลาที่นั่งรอจังหวะของตัวเอง
        self.codes = {}

    def counters(self):
        return {"requests": self.n_req, "bytes": self.n_bytes,
                "retries": self.n_retry, "failed": self.n_fail,
                # เวลาต่อรีเควสต์คือสัญญาณของการถูกหน่วงแบบค่อยเป็นค่อยไป ซึ่งไม่โผล่มาเป็นรหัส 429
                "secs": round(self.t_sum, 2),
                "codes": dict(sorted(self.codes.items()))}

    def _wait(self):
        gap = time.time() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.time()

    def get(self, url, want_json=True):
        """คืนเนื้อหา หรือ None เมื่อยิงไม่สำเร็จ — ไม่โยน exception นอกจากกรณีถูกบล็อก"""
        for attempt in range(self.retries):
            self._wait()
            self.n_req += 1
            t0 = time.time()
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    self.t_sum += time.time() - t0
                    self.n_bytes += len(raw)
                    self.codes[str(r.status)] = self.codes.get(str(r.status), 0) + 1
                    enc = r.headers.get("Content-Encoding", "")
                    body = (gzip.decompress(raw) if enc == "gzip"
                            else zlib.decompress(raw) if enc == "deflate" else raw)
                    self.streak = 0
                    return json.loads(body) if want_json else body.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                self.t_sum += time.time() - t0
                self.codes[str(e.code)] = self.codes.get(str(e.code), 0) + 1
                if e.code in (429, 500, 502, 503, 504):
                    self.n_retry += 1
                    time.sleep((5, 20, 60)[min(attempt, 2)])
                    continue
                self.streak = 0          # 404/403 ของหน้าเดียวไม่ใช่การถูกบล็อก
                return None
            except Exception as e:
                self.t_sum += time.time() - t0
                self.codes[type(e).__name__] = self.codes.get(type(e).__name__, 0) + 1
                self.n_retry += 1
                if self.verbose:
                    print(f"    ! {type(e).__name__}: {e}")
                time.sleep((2, 10, 30)[min(attempt, 2)])
        self.n_fail += 1
        self.streak += 1
        if self.streak >= self.block_after:
            raise Blocked(f"ยิงพลาดติดกัน {self.streak} ครั้ง")
        return None

    # --- ทางเรียกที่ตัวเก็บใช้จริง ---

    def feed(self, limit=100, offset=0, category=None, details=True):
        """ฟีดงานที่เปิดอยู่ · `categories[]` เท่านั้นที่กรองได้จริง ตัวสะกดอื่นถูกเมินเงียบ ๆ"""
        q = [("limit", limit), ("offset", offset)]
        if category is not None:
            q.append(("categories[]", category))
        if details:
            q += [("job_details", "true"), ("full_description", "true")]
        d = self.get(f"{API}/projects/active/?" + urllib.parse.urlencode(q))
        return ((d or {}).get("result") or {}).get("projects") or []

    def by_ids(self, ids, details=False):
        """ถามทีละไม่เกิน 60 ID · ใช้กับงานที่ปิดไปแล้วได้ และคืน status/sub_status เสมอ"""
        out = []
        ids = list(ids)
        for i in range(0, len(ids), 60):
            chunk = ids[i:i + 60]
            q = [("projects[]", x) for x in chunk]
            if details:
                q += [("job_details", "true"), ("full_description", "true")]
            d = self.get(f"{API}/projects/?" + urllib.parse.urlencode(q))
            out += ((d or {}).get("result") or {}).get("projects") or []
        return out

    def page(self, seo_url):
        """หน้าเว็บของประกาศ — แหล่งเดียวที่บอกว่าใครบิด แต่โชว์ราว 11% ของทั้งหมด"""
        return self.get(f"{WEB}/projects/{seo_url}", want_json=False)

    def user_ids(self, usernames):
        """แปลงชื่อผู้ใช้เป็น ID ตัวเลข เพื่อให้เก็บเฉพาะ ID ตามกฎของโปรเจกต์"""
        out, names = {}, list(usernames)
        for i in range(0, len(names), 50):
            q = [("usernames[]", n) for n in names[i:i + 50]]
            d = self.get(f"{USERS_API}/users/?" + urllib.parse.urlencode(q))
            for u in (((d or {}).get("result") or {}).get("users") or {}).values():
                if u.get("username") and u.get("id"):
                    out[u["username"]] = u["id"]
        return out

    def categories(self):
        """รายชื่อหมวดอ่านจาก endpoint ไม่ใช่จากการสุ่มดูฟีด (หมวด 103 ไม่เคยโผล่ในฟีดตัวอย่าง)"""
        d = self.get(f"{API}/jobs/?job_details=true")
        cats = {}
        for j in (d or {}).get("result") or []:
            c = (j or {}).get("category") or {}
            if c.get("id"):
                cats[int(c["id"])] = c.get("name")
        return cats
