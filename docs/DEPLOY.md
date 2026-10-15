# Deploy บน server

CI (GitHub Actions) build image ให้ทุกครั้งที่ push เข้า `main` แล้ว push ขึ้น GHCR
บน server ไม่มี source code เลย มีแค่ `compose.yaml`, `.env` และ `data/` แล้ว `pull` image มารัน

```
GitHub (push main) ──CI──▶ ghcr.io/<owner>/line-billing-bot:<sha|latest>
                           ghcr.io/<owner>/line-billing-backoffice-web:<sha|latest>
                                         │ docker compose pull
                                         ▼
server:  nginx ภายนอก ──line-router-net──▶ app (บอท :8500) ──▶ db (postgres ของบอท)
                                   │            └──▶ central-db (อ่านพนักงาน, read-only)
                                   └──▶ backoffice-web (:80) ──▶ backoffice-api (:8600) ──▶ db
```

---

## 1. สิ่งที่ต้องมีก่อน

| อะไร | ทำไม |
|---|---|
| Docker + Docker Compose v2 (`docker compose version`) | รัน stack |
| stack ของ central-db อยู่ที่ `<parent>/db/` และรันอยู่ | บอทอ่านตาราง `employees` ตอนลงทะเบียน |
| docker network `line-router-net` มีอยู่แล้ว (`docker network ls`) | central-db และ nginx ภายนอกอยู่ใน network นี้ compose ประกาศเป็น `external` จึงไม่สร้างให้ |
| nginx ภายนอกที่อยู่ใน `line-router-net` | รับ HTTPS จาก LINE / LIFF แล้วส่งต่อเข้าบอท |
| pipeline ที่เขียน JSON ลูกหนี้ทุกวัน 18:00 | บอทอ่านรายชื่อลูกค้าและบิลจากไฟล์นี้ (ดูข้อ 3) |
| สิทธิ์ pull จาก GHCR | ถ้า package เป็น private ต้อง login (ดูข้อ 5) |

---

## 2. วางโฟลเดอร์บน server

โฟลเดอร์ deploy ต้องอยู่ **ข้าง** โฟลเดอร์ `db/` ของ central-db เพราะ `compose.yaml` mount `../db/.env`
(ชื่อโฟลเดอร์ deploy ตั้งอะไรก็ได้)

```
<parent>/
├── db/                         ← stack ของ central-db (มีอยู่แล้ว)
│   └── .env                    ← มี POSTGRES_PASSWORD ของ central (บอท mount แบบ read-only)
└── line-billing-bot/           ← โฟลเดอร์ deploy
    ├── compose.yaml            ← copy จาก repo
    ├── .env                    ← สร้างเอง (ข้อ 4) ห้ามเข้า git
    └── data/
        └── validated/
            ├── output/         ← pipeline เขียนไฟล์ลูกหนี้ที่นี่ (ข้อ 3)
            └── slips/          ← บอทเขียนสลิปที่ผู้ใช้อัปโหลดที่นี่
```

```bash
mkdir -p line-billing-bot/data/validated/output line-billing-bot/data/validated/slips
cd line-billing-bot
# copy compose.yaml จาก repo มาไว้ที่นี่ (scp / curl จาก GitHub raw / git sparse checkout)
```

ไม่ต้องมี `app/`, `alembic/` หรือไฟล์ `.sql` บน server โค้ดและ migration อยู่ใน image แล้ว

---

## 3. ข้อมูลที่บอทอ่าน (`data/validated/output/`)

| ไฟล์ | เนื้อหา |
|---|---|
| `ar_outstanding_latest.json` | `{"customers": [{customer_code, customer_name, ..., "invoices": [...]}]}` |
| `group_latest.json` | `{"groups": [{"EmpID": "50085", "GroupID": "C301,C302"}]}` |

- บอทโหลดไฟล์นี้ตอน container เปิด และโหลดใหม่ทุกวัน **18:30** (เวลาไทย)
- ถ้าไฟล์ไม่มี บอทยังเปิดได้ แต่รายชื่อลูกค้าจะว่าง (log ขึ้น `... not found; no data loaded`)
- อยากให้โหลดไฟล์ใหม่ทันที: `docker compose restart app`

---

## 4. สร้าง `.env`

ทั้ง `app`, `db` และ `backoffice-api` อ่านไฟล์เดียวกันนี้

```dotenv
# --- Image ที่จะรัน (ระบุ tag เป็น SHA ของ commit จะ rollback ได้) ---
BOT_IMAGE=ghcr.io/<owner>/line-billing-bot:latest
BACKOFFICE_WEB_IMAGE=ghcr.io/<owner>/line-billing-backoffice-web:latest

# --- LINE Messaging API (Developers Console > channel > Basic settings) ---
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_RICH_MENU_SETUP_ENABLED=true

# URL สาธารณะของบอท รวม prefix ที่ nginx ใช้ (ใช้ทำ URL ของโลโก้ตอนลงทะเบียน)
PUBLIC_BASE_URL=https://<domain>/line-oa-test

# --- LIFF (Developers Console > LINE Login channel > LIFF) ---
LIFF_CHANNEL_ID=
BILLING_LIFF_URL=https://liff.line.me/<liff-id>
LIFF_ALLOWED_ORIGIN=

# --- DB ของบอท ---
POSTGRES_DB=line_platform_test
POSTGRES_USER=lineapp
POSTGRES_PASSWORD=<สุ่มใหม่>
DATABASE_URL=postgresql+asyncpg://lineapp:<POSTGRES_PASSWORD>@db:5432/line_platform_test

# --- Backoffice ---
BACKOFFICE_SECRET=<สุ่ม อย่างน้อย 32 ตัว>
BACKOFFICE_COOKIE_SECURE=true
```

| ตัวแปร | ต้องมี | ใส่อะไร / ข้อควรระวัง |
|---|---|---|
| `BOT_IMAGE`, `BACKOFFICE_WEB_IMAGE` | ✅ | ถ้าไม่ใส่ compose จะไม่ยอมรัน `<owner>` ต้องเป็นตัวเล็ก |
| `LINE_CHANNEL_ID`, `LINE_CHANNEL_SECRET` | ✅ | ของ Messaging API channel |
| `LINE_RICH_MENU_SETUP_ENABLED` | | `true` = ตอนเปิดระบบจะสร้าง rich menu ใหม่และ link ให้ผู้ใช้ทุกคนที่ลงทะเบียนแล้ว ตั้ง `false` ไว้ก่อนถ้าเป็น channel ใหม่ที่ยังไม่ได้ตรวจ |
| `PUBLIC_BASE_URL` | ✅ | ต้องเป็น URL ที่เข้าถึงได้จากภายนอกจริง ไม่ต้องมี `/` ปิดท้าย |
| `LIFF_CHANNEL_ID` | | channel ID ของ LINE Login channel ที่ผูกกับ LIFF (ใช้ตรวจ ID token) |
| `BILLING_LIFF_URL` | | URL ของ LIFF ที่จะเปิดตอนกดเลือกลูกค้า |
| `LIFF_ALLOWED_ORIGIN` | | เว้นว่างได้ ถ้า LIFF เรียก API ผ่าน domain เดียวกัน ใส่ origin เมื่อ LIFF อยู่คนละ domain |
| `POSTGRES_*` | ✅ | ใช้ **ตอนสร้าง volume ครั้งแรกเท่านั้น** เปลี่ยนทีหลังจะไม่มีผลกับ DB ที่มีอยู่ |
| `DATABASE_URL` | ✅ | host ต้องเป็น `db` และรหัสผ่านต้องตรงกับ `POSTGRES_PASSWORD` (`app` ถูก override เป็น `line-billing-test-db` ใน compose เพื่อไม่ให้ชนกับ `db` ของระบบอื่นใน `line-router-net`) |
| `BACKOFFICE_SECRET` | ✅ | ใช้ sign cookie ถ้าสั้นกว่า 32 ตัว backoffice จะไม่เปิด สร้างด้วย `openssl rand -hex 32` |
| `BACKOFFICE_COOKIE_SECURE` | | `true` เมื่อเข้า backoffice ผ่าน HTTPS |
| `RICH_MENU_FONT` | | path ของฟอนต์ไทย ไม่ต้องใส่ เพราะ image ติดตั้งฟอนต์ให้แล้ว |

ค่าที่ compose ตั้งให้เอง ไม่ต้องใส่ใน `.env`: `ATTACHMENT_DIR`, `DATABASE_HOST`,
`EMPLOYEE_DB_ENV_FILE` และ `TEST_TEXT_COMMANDS_ENABLED`

```bash
chmod 600 .env
```

---

## 5. Login GHCR (ถ้า package เป็น private)

สร้าง Personal Access Token (classic) ที่มีสิทธิ์ `read:packages` แล้ว:

```bash
echo <TOKEN> | docker login ghcr.io -u <github-user> --password-stdin
```

หรือตั้ง package เป็น public ที่ GitHub > Packages > package settings ก็จะไม่ต้อง login

---

## 6. รันครั้งแรก

```bash
docker compose pull
docker compose up -d
docker compose ps          # app, db, backoffice-api, backoffice-web ต้องเป็น running / healthy
docker compose logs -f app
```

ตอน `app` เปิด จะรัน `alembic upgrade head` ก่อนเสมอ ถ้า DB ว่าง migration จะสร้างทุกตารางให้
ถ้า migration ล้ม container จะหยุด (ดูสาเหตุได้จาก `docker compose logs app`)

ห้ามเพิ่ม `--workers` หรือ scale `app` เกิน 1 ตัว เพราะ session ของการส่งบิลและ lock ของผู้ใช้เก็บใน memory ของ process

---

## 7. ตั้ง nginx ภายนอก

nginx ต้องอยู่ใน `line-router-net` แล้ว proxy ไปที่ alias `line-billing-test-app:8500`
ใส่ `/` ท้าย `proxy_pass` เพื่อให้ตัด prefix ออก บอทจะได้เห็น path เป็น `/callback` และ `/api/liff/...`

```nginx
location /line-oa-test/ {
    proxy_pass http://line-billing-test-app:8500/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

| URL ภายนอก | ไปที่ |
|---|---|
| `https://<domain>/line-oa-test/callback` | webhook ของ LINE |
| `https://<domain>/line-oa-test/api/liff/...` | API ที่ LIFF เรียก |
| `https://<domain>/line-oa-test/assets/...` | โลโก้ที่ส่งตอนลงทะเบียน |
| `https://<domain>/line-oa-test/health` | ตรวจว่าบอทเปิดอยู่ |

Backoffice เปิดแค่ที่ `127.0.0.1:18510` ของ server เข้าใช้ผ่าน SSH tunnel
(`ssh -L 18510:127.0.0.1:18510 <server>` แล้วเปิด `http://localhost:18510`)
หรือทำ route ใน nginx แยก ถ้าทำ route ให้จำกัด IP และตั้ง `BACKOFFICE_COOKIE_SECURE=true`

---

## 8. ตั้งค่าใน LINE Developers Console

| ที่ | ตั้ง |
|---|---|
| Messaging API channel > Webhook URL | `https://<domain>/line-oa-test/callback` แล้วกด Verify และเปิด **Use webhook** |
| Messaging API channel > Auto-reply / Greeting | ปิด (บอทตอบเอง) |
| LINE Login channel > LIFF > Endpoint URL | URL ของหน้า LIFF (billing-liff) |
| Provider | LIFF channel กับ Messaging API channel ต้องอยู่ **provider เดียวกัน** ไม่อย่างนั้น user ID ที่ได้จาก LIFF จะไม่ตรงกับในแชต และหน้าอัปโหลดรูปจะไม่ถูกส่งเข้าแชต |

---

## 9. สร้างบัญชี backoffice

```bash
docker compose exec backoffice-api uv run --no-sync python -m backoffice.api.create_admin <username>
# role viewer: ... create_admin <username> viewer
```

คำสั่งจะถามรหัสผ่าน 2 ครั้ง (ไม่แสดงบนจอ) รันซ้ำด้วย username เดิม = reset รหัสผ่านและ role ของบัญชีนั้น

---

## 10. ตรวจว่าใช้งานได้

```bash
curl -s http://127.0.0.1:18500/health                      # {"status":"ok",...}
curl -s https://<domain>/line-oa-test/openapi.json | grep -o '/api/liff/[a-z]*'
docker compose logs app | grep -E "Running upgrade|ERROR"
```

- กด Verify webhook ใน Console ต้องขึ้น Success
- ทักบอทใน LINE ต้องได้ข้อความให้ลงทะเบียน
- ดูเวลาที่ LIFF ใช้: `docker compose logs app | grep "LIFF customer"` (มี `verify_ms`, `employee_ms`, `total_ms`)

---

## 11. Deploy รอบถัดไป / Rollback

```bash
docker compose pull
docker compose up -d --remove-orphans
```

Rollback: เปลี่ยน `BOT_IMAGE` / `BACKOFFICE_WEB_IMAGE` ใน `.env` เป็น tag SHA ของ commit ก่อนหน้า
(ดูได้ที่ GitHub > Packages) แล้วรัน `docker compose up -d`
ถ้ารอบที่จะย้อนกลับไปผ่าน migration ที่เปลี่ยน schema มาแล้ว การ rollback image อย่างเดียวอาจไม่พอ ต้องดู migration นั้นก่อน

---

## 12. ย้ายจาก setup เดิม (ทำครั้งเดียว)

server เดิมรันแบบ mount `./app` และ `--reload` มี Redis และสร้าง DB จาก backup `.sql`

1. **เช็ก migration ก่อน deploy ครั้งแรก** DB ที่มาจาก backup ถูก stamp ไว้ที่ `f2a6b8c0d4e1`:
   ```bash
   docker compose exec db psql -U lineapp -d line_platform_test -c "SELECT version_num FROM alembic_version;"
   docker compose exec db psql -U lineapp -d line_platform_test -c "SELECT column_name FROM information_schema.columns WHERE table_name='bill_sends' AND column_name='files';"
   ```
   - ยังไม่มีคอลัมน์ `files`: ไม่ต้องทำอะไร ตอนเปิด container migration จะเพิ่มให้เอง
   - มีคอลัมน์แล้ว แต่ version ยังเป็น `f2a6b8c0d4e1`: ต้อง stamp ก่อน ไม่อย่างนั้น container จะล้ม
     ```bash
     docker compose run --rm --entrypoint uv app run --no-sync alembic stamp a8c4e6f0b2d3
     ```
2. ใส่ `BOT_IMAGE` และ `BACKOFFICE_WEB_IMAGE` ลงใน `.env`
3. เปลี่ยน `compose.yaml` เป็นเวอร์ชันใหม่จาก repo
4. `docker compose up -d --remove-orphans` (คำสั่งนี้ลบ container `redis` เดิมที่ไม่ใช้แล้ว)
5. ลบ `app/`, `alembic/` และไฟล์ `.sql` ที่เคยวางไว้บน server ออกได้

volume ของ DB (`line-billing-test-postgres-data`) ใช้ตัวเดิม ข้อมูลไม่หาย

---

## 13. ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / แก้ |
|---|---|
| `set BOT_IMAGE` ตอน `up` | ยังไม่ได้ใส่ `BOT_IMAGE` / `BACKOFFICE_WEB_IMAGE` ใน `.env` |
| `pull access denied` / `unauthorized` | ยังไม่ได้ login GHCR หรือ token ไม่มีสิทธิ์ `read:packages` หรือ `<owner>` เป็นตัวใหญ่ |
| `network line-router-net declared as external, but could not be found` | stack ของ central-db ยังไม่ได้รัน หรือ network ชื่อไม่ตรง |
| `POSTGRES_PASSWORD is not set in /run/secrets/central-db.env` | วางโฟลเดอร์ deploy ไม่ได้อยู่ข้าง `db/` หรือ `../db/.env` ไม่มีค่านี้ |
| `app` restart วน และ log มี `alembic` error | migration ล้ม ดูข้อ 12.1 |
| `BACKOFFICE_SECRET must be set to at least 32 random characters` | `BACKOFFICE_SECRET` สั้นเกิน |
| LIFF ได้ 404 `Not Found` ทุก path | nginx ไม่ได้ตัด prefix (ลืม `/` ท้าย `proxy_pass`) |
| LIFF ยืนยันผ่าน แต่ไม่มีหน้าอัปโหลดรูปในแชต | LIFF กับ Messaging API อยู่คนละ provider (ข้อ 8) |
| รายชื่อลูกค้าว่าง | ไม่มีไฟล์ใน `data/validated/output/` หรือรหัสพนักงานไม่อยู่ใน `group_latest.json` |
| โลโก้ตอนลงทะเบียนไม่ขึ้น | `PUBLIC_BASE_URL` ผิด หรือไม่ได้รวม prefix `/line-oa-test` |
