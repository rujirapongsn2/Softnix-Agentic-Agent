---
name: sendmail
description: ส่งอีเมลผ่าน Resend API เมื่อผู้ใช้สั่งให้ส่งอีเมลถึงผู้รับที่กำหนด พร้อม subject และเนื้อหาแบบ text/html
---

# Sendmail Skill (Resend)

กฎสำคัญ:
- ต้องใช้สคริปต์นี้เท่านั้น: `skillpacks/sendmail/scripts/send_with_resend.py`
- ห้ามเขียนโค้ดส่งเมลใหม่แบบ ad-hoc (เช่น urllib/requests inline) เมื่อ skill นี้ถูกเลือก
- ถ้าส่งไม่สำเร็จ ให้รายงาน error จริงและหยุด ไม่ปิดงานว่าเสร็จ

ใช้ skill นี้เมื่อผู้ใช้ต้องการให้ agent ส่งอีเมลจริงผ่าน Resend API
เช่น "ส่งเมลไปหา..." หรือ "ส่งสรุปผลงานให้ทีมทางอีเมล"

## Requirements

1. ต้องมี env `RESEND_API_KEY` ใน runtime ที่จะรันสคริปต์
2. หรือเก็บ key ไว้ที่ไฟล์ `skillpacks/sendmail/.secrets/RESEND_API_KEY`
3. (optional) ตั้ง `RESEND_API_KEY_FILE` เพื่อชี้ path key file อื่น
4. ติดตั้ง package `resend` ถ้ายังไม่มี

## Workflow

1. ตรวจข้อมูลที่จำเป็น:
- ผู้ส่ง (`from`)
- ผู้รับ (`to`)
- หัวข้อ (`subject`)
- เนื้อหา (`text` หรือ `html`)
2. ถ้าไม่มี `resend` ให้ติดตั้งก่อน (`python -m pip install resend`)
3. ใช้สคริปต์ `scripts/send_with_resend.py` เพื่อส่งอีเมล
4. สรุปผลว่า success/failure พร้อม `id` ที่ได้จาก API

## Script

สคริปต์หลัก:
- `scripts/send_with_resend.py`

ตัวอย่างเรียกใช้:

```bash
python skillpacks/sendmail/scripts/send_with_resend.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "delivered@resend.dev" \
  --subject "hello world" \
  --html "<strong>it works!</strong>"
```

ถ้าต้องการส่งหลายคน:

```bash
python skillpacks/sendmail/scripts/send_with_resend.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "a@example.com,b@example.com" \
  --subject "Daily report" \
  --text "Done"
```

## Guardrails

- ห้าม hardcode API key ลงไฟล์
- ถ้าไม่มีทั้ง `RESEND_API_KEY` และ key file ให้หยุดและแจ้งผู้ใช้
- ต้องมีอย่างน้อยหนึ่งเนื้อหา (`--text` หรือ `--html`)
- ถ้าส่งไม่สำเร็จ ให้แสดง error จาก API แบบตรงไปตรงมา
