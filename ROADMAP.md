# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานถัดไป โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## P0 (ต้องทำก่อน)

1. Core Memory design (Spec + Contracts)
- เป้าหมาย: ออกแบบ Memory ที่ใช้งานเป็นธรรมชาติและยืดหยุ่น โดยผู้ใช้สั่ง “จำสิ่งนี้” ได้ทันที และ agent จัดการบันทึกให้อัตโนมัติ
- หลักการออกแบบ:
  - `Profile Memory` สำหรับ preference ระยะยาวของผู้ใช้ (เช่น tone/style/lang) จัดเก็บใน `PROFILE.md`
  - `Session Memory` สำหรับบริบทชั่วคราวของงาน/บทสนทนาปัจจุบัน จัดเก็บใน `SESSION.md`
  - `Policy Memory` เป็นกติการะดับระบบ (global) ที่กำหนดได้เฉพาะ admin/manual เท่านั้น ผู้ใช้ไม่สามารถแก้ไขหรือมองเห็นได้
- งานหลัก:
  - ออกแบบ contract การอ่าน/เขียน memory แบบ markdown-first:
    - `PROFILE.md` และ `SESSION.md` เป็น source of truth ฝั่ง user-visible
    - รองรับการเพิ่ม/อัปเดตจากภาษาธรรมชาติ เช่น “จำไว้ว่า…”, “ตั้งโทนให้…”
  - นิยาม schema เชิงตรรกะ (แม้เก็บเป็น markdown) สำหรับ parser/validator:
    - `scope`, `kind`, `key`, `value`, `priority`, `ttl`, `updated_at`, `source`
  - กำหนด write rule และ conflict resolution:
    - ลำดับความสำคัญ: `Policy > Profile > Session`
    - กรณีชนกันให้เคารพ priority + recency และ log เหตุผลการเลือกค่า
  - ออกแบบ governance สำหรับ `Policy`:
    - ไฟล์ policy อยู่ใน global path ที่ไม่ expose ผ่าน user workspace/API ปกติ
    - apply ตอน runtime startup และ refresh ได้เฉพาะช่องทาง admin
    - เพิ่ม guard ป้องกัน planner/action แก้ไข policy โดยตรง
  - กำหนด UX contract สำหรับ memory actions:
    - trigger phrase สำหรับ “บันทึกความจำ”
    - คำสั่ง explicit เช่น “ลืมสิ่งนี้”, “แก้ไขโทนการตอบ”
    - audit trail ว่า entry ไหนถูกเพิ่ม/อัปเดต/หมดอายุ
  - กำหนด filesystem contract รุ่นแรก:
    - workspace: `PROFILE.md`, `SESSION.md`
    - global: `POLICY.md` (admin-managed only, hidden from user scope)
- ผลลัพธ์:
  - ได้ spec ที่ decision-complete พร้อม sequence flow, file contract, precedence rule และ security boundary ชัดเจน
  - อ้างอิงสเปกลงมือทำ: `docs/core-memory-spec.md`

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- งานหลัก:
  - สร้าง execution runtime/sandbox สำหรับรันโค้ด (resource limits: cpu/memory/timeout/disk)
  - นิยาม action กลางสำหรับวงจร `generate -> run -> validate -> refine`
  - เพิ่ม workspace governance (input/working/output zones + artifact snapshot)
  - เพิ่ม safety policy สำหรับคำสั่งอิสระ (allow/deny + approval gate)
  - เพิ่ม structured logs/traces สำหรับแผน โค้ด คำสั่ง และผลลัพธ์ต่อ iteration
  - เพิ่ม objective validation checks และ stop conditions แบบ no-progress detection
- ผลลัพธ์: Agent ทำงาน data/code transformation แบบ end-to-end ได้ด้วยโค้ดที่สร้างเองอย่างปลอดภัยและตรวจสอบย้อนหลังได้

## P1 (ทำต่อหลัง P0)

3. CI/CD pipeline
- เป้าหมาย: คุมคุณภาพอัตโนมัติทุก PR/Push
- งานหลัก:
  - backend: `pytest`
  - frontend: `npm run build`
  - deployment: `docker compose config`
- ผลลัพธ์: ลด regression ก่อน merge

4. Monitoring/alerts for long-running runs
- เป้าหมาย: มองเห็นปัญหา run ค้าง/timeout/provider error ได้เร็ว
- งานหลัก:
  - timeout threshold
  - stuck-run detection
  - provider error counter
  - alert output (เริ่มจาก log/webhook)
- ผลลัพธ์: ดูแลระบบง่ายขึ้นและลดเวลาตรวจ incident

5. Authentication model for production
- เป้าหมาย: ยกระดับจาก static API key ไป session/token
- งานหลัก:
  - token/session lifecycle
  - secure storage strategy
  - rotate/revoke flow
- ผลลัพธ์: พร้อมใช้งาน production มากขึ้น

## P2 (เสริมความแข็งแรง)

6. Security hardening phase 2
- เป้าหมาย: เพิ่ม defense-in-depth
- งานหลัก:
  - rate limiting
  - audit log
  - request id tracing
- ผลลัพธ์: สืบสวนปัญหาและป้องกัน abuse ได้ดีขึ้น

7. Release package and runbook
- เป้าหมาย: ทำให้ทีม deploy/operate ได้มาตรฐาน
- งานหลัก:
  - versioning + changelog
  - smoke tests (dev/staging/prod)
  - operational runbook
- ผลลัพธ์: release ซ้ำได้และลด human error

## Definition of Done (ทุกหัวข้อ)

- มี test coverage ที่เกี่ยวข้อง
- อัปเดต README/เอกสาร deploy
- ผ่าน backend + frontend build/test
- มี rollback plan หรือ mitigation สำหรับการ deploy
