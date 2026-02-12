# Resend Email Skill

ส่งอีเมลผ่าน Resend API ด้วย Python

## ความต้องการ
- Python 3.8+
- `resend` package (`pip install resend`)

## การตั้งค่า
1. ใส่ API Key ไว้ที่ `skillpacks/resend-email/.secret/RESEND_API_KEY`
2. ห้าม hardcode key ในโค้ด

## การใช้งาน
```bash
python skillpacks/resend-email/scripts/send_email.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "recipient@example.com" \
  --subject "Hello" \
  --html "<strong>Hello World</strong>"
```

## Parameters
| Parameter | Required | Description |
|-----------|----------|-------------|
| --from    | Yes      | Sender address (e.g. `Name <email@domain>`) |
| --to      | Yes      | Recipient email(s), comma-separated |
| --subject | Yes      | Email subject line |
| --html    | Yes      | HTML body content |

## Security
- API key ถูกอ่านจากไฟล์ `.secret/RESEND_API_KEY`
- โฟลเดอร์ `.secret` ต้องไม่ถูก commit เข้า git
