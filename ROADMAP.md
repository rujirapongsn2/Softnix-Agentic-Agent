# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานถัดไป โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## P0 (ต้องทำก่อน)

1. Artifacts UX parity (Web UI)
- เป้าหมาย: ใช้งาน artifacts ได้ครบเท่า desktop/CLI
- งานหลัก:
  - เพิ่ม metadata (size, modified time)
  - เพิ่ม search/filter และ sort ใน sidebar
  - เพิ่มสถานะ `downloading/empty/error` ที่ชัดเจน
- ผลลัพธ์: ค้นหาและดาวน์โหลดไฟล์ผลลัพธ์ได้เร็วและแม่นยำ

2. Core Memory design (Spec + Contracts)
- เป้าหมาย: ออกแบบ Memory ใน Agent Core โดยยังไม่ลง implementation เต็ม
- งานหลัก:
  - กำหนด model: `Session`, `Profile`, `Policy`
  - กำหนด schema มาตรฐาน: `scope`, `kind`, `key`, `value`, `priority`, `ttl`
  - กำหนด conflict resolution และ write-guard policy
  - กำหนด filesystem contract สำหรับ memory store รุ่นแรก
- ผลลัพธ์: ได้ spec ที่ decision-complete พร้อมส่งต่อ implement

3. Autonomous code execution framework (No special-purpose tools)
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

4. CI/CD pipeline
- เป้าหมาย: คุมคุณภาพอัตโนมัติทุก PR/Push
- งานหลัก:
  - backend: `pytest`
  - frontend: `npm run build`
  - deployment: `docker compose config`
- ผลลัพธ์: ลด regression ก่อน merge

5. Monitoring/alerts for long-running runs
- เป้าหมาย: มองเห็นปัญหา run ค้าง/timeout/provider error ได้เร็ว
- งานหลัก:
  - timeout threshold
  - stuck-run detection
  - provider error counter
  - alert output (เริ่มจาก log/webhook)
- ผลลัพธ์: ดูแลระบบง่ายขึ้นและลดเวลาตรวจ incident

6. Authentication model for production
- เป้าหมาย: ยกระดับจาก static API key ไป session/token
- งานหลัก:
  - token/session lifecycle
  - secure storage strategy
  - rotate/revoke flow
- ผลลัพธ์: พร้อมใช้งาน production มากขึ้น

## P2 (เสริมความแข็งแรง)

7. Security hardening phase 2
- เป้าหมาย: เพิ่ม defense-in-depth
- งานหลัก:
  - rate limiting
  - audit log
  - request id tracing
- ผลลัพธ์: สืบสวนปัญหาและป้องกัน abuse ได้ดีขึ้น

8. Release package and runbook
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
