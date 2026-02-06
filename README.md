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
pip install -e .[dev]
```

## ตั้งค่า Environment

คัดลอก `.env.example` และกำหนดค่า API key ตาม provider ที่ใช้

ตัวอย่างที่ต้องมี:
- `SOFTNIX_OPENAI_API_KEY` เมื่อใช้ `openai`
- `SOFTNIX_CLAUDE_API_KEY` เมื่อใช้ `claude`
- `SOFTNIX_CUSTOM_BASE_URL` (+ optional key) เมื่อใช้ `custom`

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
- `GET /runs/{id}` อ่านสถานะ run
- `GET /runs/{id}/iterations` อ่าน iteration logs
- `POST /runs/{id}/cancel` ส่งคำขอหยุด run

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

ข้อจำกัด:
- ห้าม path ออกนอก workspace
- shell command ต้องอยู่ใน allowlist (`SOFTNIX_SAFE_COMMANDS`)
- token เสี่ยง (`rm`, `sudo`, `curl`, `wget`, `ssh`, `scp`, `mv`) ถูก block

## หมายเหตุสำหรับ Desktop/Web

รุ่นนี้ยังไม่สร้าง UI แต่โครงสร้าง core และ REST contract พร้อมสำหรับนำไปต่อยอดเป็น Desktop Application และ Web Application
