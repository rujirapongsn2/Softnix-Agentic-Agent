# Get Sale Order Skill
ใช้ skill นี้เมื่อผู้ใช้ต้องการดึงข้อมูล Sale Order ของบริษัท Softnix

## API Endpoints
- Base URL: `http://192.168.10.123:3000/api/documents`

## Supported Query Parameters
1. ย้อนหลัง 7 วัน — `?days=7`
2. ย้อนหลัง 30 วัน — `?days=30`
3. ช่วงวันที่ระบุเอง — `?startDate=2024-01-01&endDate=2024-01-31`
4. Payout Date ย้อนหลัง 7 วัน — `?days=7&dateType=payout`

## Workflow
1. เรียกสคริปต์: `python get-saleorder/scripts/get_saleorder.py --days 7`
2. ผลลัพธ์จะถูกบันทึกที่ `get_saleorder/resp.json`

## Security model
- Session token อยู่ที่ `skillpacks/get-saleorder/.secret/SESSION_TOKEN`
- ห้าม hardcode token ในโค้ด/prompt
- โฟลเดอร์ `.secret` ต้องไม่ถูก commit เข้า git

## Dependencies
- Python package: `requests`

## Usage Examples
```bash
# ย้อนหลัง 7 วัน
python get-saleorder/scripts/get_saleorder.py --days 7

# ย้อนหลัง 30 วัน
python get-saleorder/scripts/get_saleorder.py --days 30

# ช่วงวันที่ระบุเอง
python get-saleorder/scripts/get_saleorder.py --start-date 2024-01-01 --end-date 2024-01-31

# Payout Date ย้อนหลัง 7 วัน
python get-saleorder/scripts/get_saleorder.py --days 7 --date-type payout
```
