# Softnix Agentic Agent

CLI-first agent framework ที่ทำงานตาม flow:

`Task -> Agent Loop -> Filesystem Persistence -> Loop ต่อ`

รองรับ:
- Skills มาตรฐาน `SKILL.md`
- LLM Providers: `OpenAI`, `Claude`, `OpenAI-compatible custom endpoint`
- Safe action execution (allowlist)
- Local REST API facade สำหรับต่อยอด Desktop/Web

## โครงสร้างหลัก

- `src/softnix_agentic_agent/cli.py` คำสั่ง CLI
- `src/softnix_agentic_agent/agent/loop.py` วน iteration หลัก
- `src/softnix_agentic_agent/agent/planner.py` เรียก LLM เพื่อวางแผน action
- `src/softnix_agentic_agent/agent/executor.py` execute action แบบปลอดภัย
- `src/softnix_agentic_agent/storage/filesystem_store.py` persist state/iterations/events
- `src/softnix_agentic_agent/skills/*` parser/loader สำหรับ `SKILL.md`
- `src/softnix_agentic_agent/providers/*` adapter ของ provider
- `src/softnix_agentic_agent/api/app.py` REST facade

## ติดตั้ง

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## ตั้งค่า Environment

คัดลอก `.env.example` และกำหนดค่า API key ตาม provider ที่ใช้
ตัวระบบจะโหลดไฟล์ `.env` อัตโนมัติจาก current working directory ตอนรันคำสั่ง `softnix`

ตัวอย่างที่ต้องมี:
- `SOFTNIX_OPENAI_API_KEY` เมื่อใช้ `openai`
- `SOFTNIX_CLAUDE_API_KEY` เมื่อใช้ `claude`
- `SOFTNIX_CUSTOM_BASE_URL` (+ optional key) เมื่อใช้ `custom`

ตัวเลือกด้าน security:
- `SOFTNIX_API_KEY` เปิด API key protection ให้ทุก endpoint (ยกเว้น `/health`, `/docs`, `/openapi.json`)
- `SOFTNIX_CORS_ORIGINS` กำหนด origin ที่อนุญาต (comma-separated)
- `SOFTNIX_CORS_ALLOW_CREDENTIALS` (`true`/`false`)

## การใช้งาน CLI

### 1) Run task

```bash
softnix run --task "Build a Python course" --provider openai --max-iters 10 --workspace . --skills-dir examples/skills
```

### 2) Resume run เดิม

```bash
softnix resume --run-id <run_id>
```

### 3) List skills

```bash
softnix skills list --path examples/skills
```

### 4) เปิด API

```bash
softnix api serve --host 127.0.0.1 --port 8787
```

## REST API

- `POST /runs` เริ่ม run ใหม่
- `GET /runs` อ่านรายการ runs
- `GET /runs/{id}` อ่านสถานะ run
- `GET /runs/{id}/iterations` อ่าน iteration logs
- `GET /runs/{id}/stream` stream ความคืบหน้าแบบ SSE
- `GET /runs/{id}/stream?last_event_id=<n>` resume stream จาก event id ล่าสุด
- `GET /runs/{id}/events` อ่าน events log
- `POST /runs/{id}/cancel` ส่งคำขอหยุด run
- `POST /runs/{id}/resume` สั่ง resume run
- `GET /skills` อ่านรายการ skills
- `GET /artifacts/{id}` อ่านรายการ artifacts
- `GET /artifacts/{id}/{path}` ดาวน์โหลด artifact
- `GET /health` ตรวจสถานะ provider connectivity/config
- `GET /system/config` อ่าน effective runtime config (safe fields)

เมื่อเปิด `SOFTNIX_API_KEY`:
- ทุก request ที่เข้าถึง API หลักต้องส่ง header `x-api-key: <your-key>`
- CORS preflight (`OPTIONS`) ยังทำงานได้ปกติสำหรับ origin ที่ allow ไว้

## Web UI (ChatGPT-like)

โฟลเดอร์ `web-ui/` เป็น frontend สำหรับใช้งานกับ API backend โดยใช้:
- React + Vite
- Tailwind CSS + shadcn-style components
- Framer Motion animations
- Streaming markdown renderer และ AI-native UI blocks

### รัน Backend

```bash
softnix api serve --host 127.0.0.1 --port 8787
```

ควรเปิด `venv` ก่อนทุกครั้ง:

```bash
source .venv/bin/activate
```

### รัน Web UI

```bash
cd web-ui
npm install
npm run dev
```

ค่า default API คือ `http://127.0.0.1:8787` และ override ได้ด้วย env:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8787
VITE_SOFTNIX_API_KEY=
```

### เข้าใช้งาน Web UI

1. เปิดเบราว์เซอร์ที่ `http://127.0.0.1:5173`
2. กรอก task/provider/model แล้วกด `Start Run`
3. ดู conversation timeline และใช้ปุ่ม `Cancel`/`Resume` ได้ตรงนี้เลย

## รูปแบบไฟล์ Persistence

สำหรับแต่ละ run จะถูกเก็บที่:

- `.softnix/runs/<run_id>/state.json`
- `.softnix/runs/<run_id>/iterations.jsonl`
- `.softnix/runs/<run_id>/artifacts/`
- `.softnix/runs/<run_id>/events.log`

## Safe Execution Policy

Action ที่รองรับในรุ่นแรก:
- `list_dir`
- `read_file`
- `write_workspace_file`
- `run_safe_command`
- `web_fetch`

ข้อจำกัด:
- ห้าม path ออกนอก workspace
- shell command ต้องอยู่ใน allowlist (`SOFTNIX_SAFE_COMMANDS`)
- token เสี่ยง (`sudo`, `curl`, `wget`, `ssh`, `scp`, `mv`) ถูก block
- `rm` อนุญาตเมื่ออยู่ใน allowlist และลบได้เฉพาะ path ภายใน workspace

## หมายเหตุสำหรับ Desktop/Web

รุ่นนี้ยังไม่สร้าง UI แต่โครงสร้าง core และ REST contract พร้อมสำหรับนำไปต่อยอดเป็น Desktop Application และ Web Application
