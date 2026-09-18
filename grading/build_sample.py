#!/usr/bin/env python3
"""ตัดชุดทดสอบของด่านหนึ่งออกจากกองข้อมูล แล้วแช่แข็งไว้เป็นไฟล์เดียว

ด่านหนึ่งถามว่า *ผู้อ่านคนเดิมนิ่งไหม* ไม่ได้ถามว่าไม้บรรทัดถูกไหม ชุดทดสอบจึงต้องนิ่ง
ที่สุดเท่าที่ทำได้ — งานชุดเดิมเป๊ะทั้งห้ารอบ ตัดครั้งเดียวแล้วเก็บไฟล์ไว้ ห้ามสุ่มใหม่ระหว่างทาง
เพราะถ้าชุดขยับ ความไม่นิ่งที่วัดได้จะแยกไม่ออกว่ามาจากผู้อ่านหรือมาจากชุด

**ที่ส่งออกไปให้ตัวอ่านมีแค่คำอธิบายกับแท็ก** ไม่มีหมายเลขงาน ลิงก์ ชื่อผู้ว่าจ้าง หรืองบ
อ้างกลับด้วยหมายเลขลำดับในชุด (`n`) เท่านั้น แผนที่ `n` → หมายเลขงานจริงถูกเขียนแยกไฟล์
และไม่เคยถูกส่งออกไปไหน

ผลลัพธ์เป็นคำอธิบายที่ลูกค้าเขียน **ห้าม commit เข้า repo นี้** เขียนลงนอก repo หรือใน `grading/out/`

  python3 grading/build_sample.py --data-dir <โคลนของ repo ข้อมูล> --out grading/out
"""
import argparse, glob, json, os, random, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "freelance-market"))
from store import read_rows        # noqa: E402

# แท็กที่นับว่าเป็นวิชาชีพกราฟิกดีไซน์ — รายชื่อนี้เป็นของด่านหนึ่งเท่านั้น
# รายชื่อวิชาชีพตัวจริงต้องตัดจากการนับแท็กที่อยู่ด้วยกันในงานจริง ซึ่งเป็นงานหลังด่านหนึ่งผ่าน
DESIGN = {
    "Graphic Design", "Logo Design", "Illustrator", "Adobe Illustrator", "Photoshop",
    "Illustration", "Brochure Design", "Banner Design", "Poster Design", "Flyer Design",
    "Brand Management", "Corporate Identity", "Packaging Design", "Book Artist",
    "Business Cards", "Adobe InDesign", "Typography", "Label Design", "Print",
}
# งานที่ติดแท็กดีไซน์แต่เนื้อในเป็นงานเขียนโปรแกรม — คัดออกตั้งแต่ต้น เพราะไม้บรรทัดใบนี้
# เป็นของกราฟิกดีไซน์ ไม่ใช่ของสายไอที และงานพวกนี้จะไปกองรวมกับ `off` จนอ่านผลไม่ออก
DEV = {
    "PHP", "HTML", "Web Development", "JavaScript", "Mobile App Development", "WordPress",
    "Python", "Software Architecture", "CSS", "React.js", "Node.js", "MySQL",
}

# งานที่ถูกใช้เป็นตัวอย่างยึดขั้นในไม้บรรทัด — ต้องไม่หลุดเข้าชุดทดสอบ ไม่งั้นด่านหนึ่งจะวัด
# ความจำของตัวอ่านแทนความนิ่งของมัน รายชื่อนี้ต้องขยับตามทุกครั้งที่ไม้บรรทัดเปลี่ยนตัวอย่าง
ANCHORS = {
    40708230, 40718370,            # K1
    40707598, 40703336,            # K2
    40703417, 40713756,            # K3
    40697019, 40689892,            # K4
    40709092, 40703923, 40699459, 40714655, 40704260, 40695408, 40695219, 40674934,   # แกน D
}

MIN_CHARS = 120      # สั้นกว่านี้ไม่มีอะไรให้อ่าน ความไม่นิ่งจะมาจากความว่างเปล่าไม่ใช่จากผู้อ่าน
MAX_CHARS = 1600     # ตัดหางเพื่อคุมขนาดชุดให้อยู่ในหน้าต่าง 128k ค่ากลางของสายนี้อยู่ราว 963


def load_projects(data_dir):
    """งานไม่ซ้ำทุกตัวจากสายประกาศ — แถวหลังทับแถวก่อนตามปกติของสายนี้"""
    seen = {}
    for p in sorted(glob.glob(os.path.join(data_dir, "*", "listings.jsonl.gz"))):
        for r in read_rows(p):          # ไฟล์ของวันปัจจุบันอ่านไม่จบเป็นเรื่องปกติ
            pr = r.get("p") or {}
            if pr.get("id"):
                seen[pr["id"]] = pr
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True, help="โฟลเดอร์ผลลัพธ์ ต้องไม่ถูก commit")
    ap.add_argument("--size", type=int, default=50, help="ขนาดชุดต่อการเรียกหนึ่งครั้ง")
    ap.add_argument("--seed", type=int, default=20260918)
    a = ap.parse_args()

    projects = load_projects(a.data_dir)
    pool = []
    for pr in projects.values():
        names = [j.get("name") for j in (pr.get("jobs") or []) if j.get("name")]
        if not (set(names) & DESIGN):
            continue
        if len(set(names) & DEV) >= 2:
            continue
        if pr["id"] in ANCHORS:
            continue
        desc = re.sub(r"[ \t]+", " ", (pr.get("description") or "").strip())
        if len(desc) < MIN_CHARS:
            continue
        pool.append({"id": pr["id"], "tags": names, "desc": desc[:MAX_CHARS]})

    pool.sort(key=lambda r: r["id"])          # เรียงก่อนสุ่ม ไม่งั้นลำดับที่ dict คืนมาทำให้ seed ไม่มีความหมาย
    random.Random(a.seed).shuffle(pool)
    if len(pool) < a.size:
        sys.exit(f"กองมีแค่ {len(pool)} งาน ไม่พอ {a.size}")
    picked = pool[:a.size]

    os.makedirs(a.out, exist_ok=True)
    items = [{"n": i + 1, "tags": r["tags"], "desc": r["desc"]} for i, r in enumerate(picked)]
    sample = {"seed": a.seed, "size": a.size, "profession": "graphic-design", "items": items}
    with open(os.path.join(a.out, "sample.json"), "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=1)
    # แผนที่กลับไปหางานจริง อยู่ฝั่งเราเท่านั้น ไม่เคยถูกส่งออก
    with open(os.path.join(a.out, "sample_ids.json"), "w", encoding="utf-8") as f:
        json.dump({str(i + 1): r["id"] for i, r in enumerate(picked)}, f, indent=1)

    lens = sorted(len(r["desc"]) for r in picked)
    print(f"กองที่เข้าเกณฑ์ {len(pool)} งาน · ตัดมา {len(picked)} งาน")
    print(f"ความยาวคำอธิบาย ค่ากลาง {lens[len(lens)//2]} ตัวอักษร สั้นสุด {lens[0]} ยาวสุด {lens[-1]}")
    print(f"รวมทั้งชุด {sum(lens)} ตัวอักษร ≈ {sum(lens)//4} โทเคน")
    print(f"เขียนแล้ว {a.out}/sample.json และ {a.out}/sample_ids.json")


if __name__ == "__main__":
    main()
