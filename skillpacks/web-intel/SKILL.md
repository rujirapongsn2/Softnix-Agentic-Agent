---
name: web-intel
description: รวบรวมข้อมูลเว็บแบบ fetch-first และ fallback ไป browser automation เมื่อข้อมูลจาก web_fetch ไม่เพียงพอ
---

# Web Intelligence Skill

ใช้ skill นี้เมื่อผู้ใช้ต้องการค้นหา/รวบรวม/สรุปข้อมูลจากเว็บไซต์ และมีโอกาสที่เว็บเป็น dynamic (SPA, content โหลดทีหลัง)

## Workflow

1. เริ่มด้วย `web_fetch` ก่อนเสมอ
2. ประเมินความเพียงพอของข้อมูลจากผล fetch
3. ถ้าไม่พอ ให้เรียก adapter script:
`web-intel/scripts/web_intel_fetch.py`
4. ใช้ไฟล์ผลลัพธ์ใน `web_intel/` เป็น evidence ก่อนสรุป

## Adapter Script

ตัวอย่างคำสั่ง:

```bash
python web-intel/scripts/web_intel_fetch.py \
  --url "https://example.com" \
  --task-hint "สรุปข้อมูลสินค้าและจุดเด่น" \
  --out-dir "web_intel"
```

artifact ที่คาดหวัง:
- `web_intel/raw.html`
- `web_intel/extracted.txt`
- `web_intel/summary.md`
- `web_intel/meta.json`

## Fallback Behavior

- ถ้าข้อมูล fetch ไม่พอและไม่มี browser adapter ให้บอกข้อจำกัดอย่างตรงไปตรงมา
- เมื่อ script แสดง `fallback_required=true` ให้ถือเป็น degraded success แล้วอ่าน `web_intel/summary.md` + `web_intel/meta.json` เพื่อนำไปสรุปต่อ
- ถ้าต้องการเปิด browser adapter จริง ให้กำหนด env:
`SOFTNIX_WEB_INTEL_BROWSER_CMD_TEMPLATE`

ตัวอย่าง template:

```bash
SOFTNIX_WEB_INTEL_BROWSER_CMD_TEMPLATE='agent-browser extract --url "{url}" --out "{out_dir}"'
```

## Rules

- ห้ามแต่งข้อมูลที่ไม่มี evidence ใน artifacts
- ระบุเหตุผล fallback จาก `meta.json` เมื่อมี
- รักษา output ให้สั้น ชัดเจน และตรวจสอบได้
