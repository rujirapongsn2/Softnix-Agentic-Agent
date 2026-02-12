---
name: tavily-search
description: ค้นหาข้อมูลบนเว็บด้วย Tavily Search API และสรุปผลเป็นไฟล์ใน workspace
---

# Tavily Search Skill

ใช้ skill นี้เมื่อผู้ใช้ต้องการค้นหาข้อมูลเว็บแบบสดและต้องการแหล่งอ้างอิงที่อ่านต่อได้

## Security model
- API key อยู่ที่ `skillpacks/tavily-search/.secret/TAVILY_API_KEY`
- ห้าม hardcode key ในโค้ด/prompt
- โฟลเดอร์ `.secret` ต้องไม่ถูก commit เข้า git

## Workflow
1. เรียกสคริปต์:
   - `run_python_code` โดยใช้ path: `tavily-search/scripts/tavily_search.py`
2. ส่งอาร์กิวเมนต์อย่างน้อย:
   - `--query "<query>"`
3. ระบุ output file:
   - `--output tavily_result.json`
4. หลังรันเสร็จอ่านไฟล์ผลลัพธ์และสรุปให้ผู้ใช้

## Example action
```json
{
  "name": "run_python_code",
  "params": {
    "path": "tavily-search/scripts/tavily_search.py",
    "args": ["--query", "ข่าว AI วันนี้", "--max-results", "5", "--output", "tavily_result.json"]
  }
}
```
