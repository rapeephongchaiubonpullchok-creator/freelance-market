#!/usr/bin/env python3
"""ตรวจว่า Freelancer.com ตอบจากสภาพแวดล้อมที่รันอยู่ไหม อ่านอย่างเดียว ไม่เก็บข้อมูล

ตอบสามคำถามที่ดีไซน์ทั้งหมดแขวนอยู่:
  1. API สาธารณะตอบไหม และเร็วแค่ไหน
  2. การถามทีละ 60 ID ใช้ได้ไหม
  3. หน้าเว็บของประกาศโหลดได้ไหม และมีบล็อกบิดฝังมาด้วยหรือเปล่า

ออกจากโปรแกรมด้วยรหัสไม่เป็นศูนย์เมื่อขาไหนขาหนึ่งใช้ไม่ได้ เพื่อให้ Actions ขึ้นแดง
"""
import json, re, sys, time, urllib.request, urllib.error

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
API = "https://www.freelancer.com/api/projects/0.1"
fail = []


def get(url, want_json=True):
    """คืน (รหัสสถานะ, วินาทีที่ใช้, ไบต์ที่ได้, เนื้อหา) โดยไม่โยน exception ขึ้นไป"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                import gzip
                body = gzip.decompress(raw)
            elif enc == "deflate":
                import zlib
                body = zlib.decompress(raw)
            else:
                body = raw
            dt = time.time() - t0
            return r.status, dt, len(raw), (json.loads(body) if want_json else body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0, 0, None
    except Exception as e:                       # timeout, DNS, TLS, บล็อกที่ชั้นเครือข่าย
        print(f"    ! {type(e).__name__}: {e}")
        return None, time.time() - t0, 0, None


def check(label, ok, detail):
    print(f"  {'ผ่าน' if ok else 'ไม่ผ่าน'}  {label}: {detail}")
    if not ok:
        fail.append(label)


print("=" * 66)
print("1) ฟีดงานที่เปิดอยู่")
code, dt, size, d = get(f"{API}/projects/active/?limit=5")
projects = (d or {}).get("result", {}).get("projects", [])
check("projects/active", code == 200 and bool(projects),
      f"http={code} {dt:.2f}s {size}B ได้ {len(projects)} งาน")
if not projects:
    print("\nฟีดใช้ไม่ได้ — ขาอื่นทดสอบต่อไม่ได้")
    sys.exit(1)
newest = max(p["id"] for p in projects)
print(f"    ID ล่าสุด {newest}")

print("\n2) ถามทีละ 60 ID")
base = newest - 400_000
q = "&".join(f"projects[]={base + i * 7}" for i in range(60))
code, dt, size, d = get(f"{API}/projects/?{q}")
found = (d or {}).get("result", {}).get("projects", [])
check("projects/?projects[]", code == 200 and bool(found),
      f"http={code} {dt:.2f}s เจอ {len(found)}/60")

print("\n3) หน้าเว็บของประกาศ")
seo = projects[0].get("seo_url")
code, dt, size, html = get(f"https://www.freelancer.com/projects/{seo}", want_json=False)
has_block = bool(html and re.search(r'"bids"\s*:\s*\[', html))
check("หน้าเว็บ", code == 200, f"http={code} {dt:.2f}s {size}B บนสาย")
check("บล็อกบิดในหน้า", has_block, "พบ" if has_block else "ไม่พบ (อาจถูกเสิร์ฟหน้าคนละแบบ)")

print("\n4) ยิงติดกัน 8 ครั้ง ดูว่าโดนจำกัดอัตราไหม")
codes, t0 = [], time.time()
for i in range(8):
    c, _, _, _ = get(f"{API}/projects/active/?limit=1")
    codes.append(str(c))
    time.sleep(0.4)
uniq = sorted(set(codes))
check("ยิงติดกัน", uniq == ["200"],
      f"{time.time() - t0:.1f}s รหัสที่ได้ {' '.join(codes)}")

print("=" * 66)
if fail:
    print("ไม่ผ่าน: " + ", ".join(fail))
    sys.exit(1)
print("ผ่านทุกข้อ — สภาพแวดล้อมนี้ยิงได้")
