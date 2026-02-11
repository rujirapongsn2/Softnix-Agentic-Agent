# Web Intelligence Fallback Spec

เอกสารนี้กำหนดแนวทางเพิ่มความสามารถค้นหา/รวบรวมข้อมูลจากเว็บไซต์แบบ 2 ชั้น:
- ชั้น 1: `web_fetch` (เร็ว/ต้นทุนต่ำ)
- ชั้น 2: browser automation adapter (เช่น `agent-browser`) เมื่อข้อมูลจากชั้น 1 ไม่เพียงพอ

## 1) เป้าหมาย

1. ลดเคสสรุปเว็บผิดพลาดจากเว็บที่ render ด้วย JavaScript
2. คงประสิทธิภาพโดยพยายาม `web_fetch` ก่อนเสมอ
3. เพิ่มความโปร่งใสด้วยเหตุผล fallback และ evidence artifacts

## 2) หลักการทำงาน

1. `fetch-first`
- เริ่มด้วย `web_fetch` สำหรับทุกงานเว็บตามปกติ

2. `quality-gated fallback`
- ยกระดับเป็น browser mode เมื่อผล `web_fetch` ไม่ผ่านเกณฑ์คุณภาพ

3. `deterministic outputs`
- ทุกโหมดต้องคืนผลลัพธ์ในรูปแบบ artifacts ที่คาดเดาได้

## 3) Quality Gates (เกณฑ์ตัดสินใจ fallback)

ระบบควร fallback เมื่อเข้าเงื่อนไขอย่างน้อย 1 ข้อ:

1. เนื้อหาสั้นผิดปกติ
- `content_length < N` (เช่น 1200 ตัวอักษร หลัง clean text)

2. ไม่พบสัญญาณเนื้อหาหลัก
- ไม่พบ heading/body markers ที่คาดไว้จาก task

3. พบ shell/page template มากกว่าเนื้อหา
- มีข้อความ boilerplate สูง และมีข้อมูลจริงต่ำ

4. Objective validation ไม่ผ่าน
- เช่นต้องมีหัวข้อ/คำสำคัญ/ตาราง แต่ไม่พบ

5. Domain policy บังคับ browser
- โดเมนใน allowlist ที่เป็น dynamic-heavy

## 4) Integration Design

## 4.1 Adapter Strategy

เชื่อม browser capability ผ่าน skill/script adapter ไม่แก้ core loop มากเกินจำเป็น:
- `skillpacks/web-intel/scripts/browser_extract.sh` (หรือ `.py`)
- รับ input: `url`, `task_hint`, `selectors(optional)`
- คืน output files ลง workspace

## 4.2 Action Path

ใช้ action กลางที่มีอยู่ (`run_safe_command` หรือ `run_python_code`) เพื่อเรียก adapter:
- อยู่ใต้ allowlist
- อยู่ใน workspace boundary
- ไม่เพิ่ม special-purpose tool ใหม่ใน core

## 4.3 Output Contract

อย่างน้อยต้องมี:
- `web_intel/raw.html`
- `web_intel/snapshot.json`
- `web_intel/extracted.txt`
- `web_intel/summary.md`
- `web_intel/meta.json` (ระบุ mode=`web_fetch|browser_fallback`, reason, timestamps)

## 4.4 Implementation Sequence (Important)

ลำดับ implement ที่แนะนำ:

1. Step 1: Skill-first
- ใช้ skill/script adapter ก่อน
- เรียกผ่าน action เดิม (`run_safe_command`/`run_python_code`)
- เป้าหมายคือส่งมอบเร็ว และ validate การใช้งานจริงก่อน

2. Step 2: Runtime hardening
- เมื่อ flow เสถียรแล้ว ค่อยแยก container runtime profile สำหรับ browser tasks
- ย้าย browser dependency หนักออกจาก runtime ทั่วไป
- เพิ่ม isolation/observability/performance tuning

## 5) Observability & Audit

เพิ่ม event/log มาตรฐาน:
- `web_intel mode=web_fetch|browser_fallback`
- `web_intel fallback_reason=<...>`
- `web_intel duration_ms=<...>`

ค่าที่ควรเก็บ:
- fallback rate ต่อโดเมน
- success rate per mode
- median duration per mode
- token/cost estimate (ถ้ามี)

## 6) Security & Runtime

1. Browser runtime ควรแยก profile/image ชัดเจน
- deps browser อยู่ image เฉพาะ

2. จำกัด network/timeout/retry
- timeout ต่อ step และ timeout รวม
- retry แบบ bounded

3. Secrets policy
- ห้ามฝัง key ใน script
- ส่งผ่าน env allowlist เท่านั้น

## 7) Rollout Plan

Phase 1 (Integration):
1. เพิ่ม skill adapter + output contract (ยังไม่แยก runtime profile)
2. ต่อกับ task เว็บชุดหลัก
3. เก็บ artifacts/evidence ครบ

Phase 2 (Decision Engine):
1. เพิ่ม quality gates + fallback reasons
2. เพิ่ม per-domain policy
3. ปรับ objective validation ให้รองรับเว็บ dynamic

Phase 3 (Hardening):
1. runtime profile/browser image (ย้ายจาก skill-only mode ไป profile เฉพาะ)
2. benchmark และ tune thresholds
3. monitoring alerts สำหรับ fallback failure

## 8) Test Plan

1. Unit tests
- quality gate evaluator
- fallback decision logic
- output contract validator

2. Integration tests
- static site: ต้องจบที่ `web_fetch`
- dynamic site: ต้อง fallback และได้ข้อมูลครบ

3. E2E tests
- task จาก Telegram schedule -> run -> summary + artifacts สำเร็จ

## 9) Definition of Done

1. `web_fetch` และ fallback ทำงานร่วมกันตามเกณฑ์
2. มี evidence artifacts ครบตาม contract
3. มี log/metrics สำหรับ debug และวัดผล
4. มีเอกสารใช้งานใน README และ roadmap อัปเดต
