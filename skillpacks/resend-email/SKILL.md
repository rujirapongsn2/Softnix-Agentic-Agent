---
name: resend-email
description: ใช้ skill นี้เมื่อผู้ใช้ต้องการส่งอีเมลผ่าน Resend API
success_artifacts:
  - resend_email/result.json
---

# Resend Email Skill

ใช้ skill นี้เมื่อผู้ใช้ต้องการส่งอีเมลผ่าน Resend API

## Security model
- API key อยู่ที่ `skillpacks/resend-email/.secret/RESEND_API_KEY`
- ห้าม hardcode key ในโค้ด/prompt
- โฟลเดอร์ `.secret` ต้องไม่ถูก commit เข้า git

## Dependencies
- Python package: `resend`
- ติดตั้งด้วย: `pip install resend`

## Workflow
1. อ่าน API key จาก `.secret/RESEND_API_KEY`
2. เรียกสคริปต์:
   ```
   python resend-email/scripts/send_email.py --to "recipient@example.com" --subject "Subject" --html "<p>Body</p>" --out-dir "resend_email"
   ```
3. ตรวจสอบผลลัพธ์จาก stdout

## Parameters
| Parameter | Required | Description |
|-----------|----------|-------------|
| --from    | No       | Sender address (fallback: `RESEND_FROM_EMAIL` หรือ `Acme <onboarding@resend.dev>`) |
| --to      | Yes      | Comma-separated recipient emails |
| --subject | Yes      | Email subject line |
| --html    | Yes      | HTML body content |
| --out-dir | No       | Directory to save result JSON (default: resend_email) |

## Output
- ผลลัพธ์จะถูกบันทึกใน `<out-dir>/result.json`
- stdout จะแสดงสถานะการส่ง
