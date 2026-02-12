# Resend Email Skill - ตัวอย่างการใช้งาน

## การใช้งานพื้นฐาน

```bash
python skillpacks/resend-email/scripts/send_email.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "recipient@example.com" \
  --subject "Test Email" \
  --html "<strong>Hello!</strong><p>This is a test email.</p>"
```

## ส่งหลายคน

```bash
python skillpacks/resend-email/scripts/send_email.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "user1@example.com,user2@example.com" \
  --subject "Team Update" \
  --html "<h1>Update</h1><p>Important announcement.</p>"
```

## กำหนด output directory

```bash
python skillpacks/resend-email/scripts/send_email.py \
  --from "Acme <onboarding@resend.dev>" \
  --to "user@example.com" \
  --subject "Report" \
  --html "<p>See attached report.</p>" \
  --out-dir my_results
```

## ตั้งค่า API Key

1. ใส่ API key ในไฟล์ `skillpacks/resend-email/.secret/RESEND_API_KEY`
2. หรือตั้ง environment variable: `export RESEND_API_KEY=re_xxxxxxxx`

## ผลลัพธ์

หลังส่งสำเร็จ จะได้ไฟล์ `result.json` ใน output directory:
```json
{
  "status": "success",
  "response": {
    "id": "email-id-here"
  }
}
```
