# Deploy บน server

CI (GitHub Actions) build image ให้ทุกครั้งที่ push เข้า `main` แล้ว push ขึ้น GHCR
บน server ไม่มี source code เลย มีแค่ `compose.yaml`, `.env` และ `data/` แล้ว `pull` image มารัน

```
GitHub (push main) ──CI──▶ ghcr.io/<owner>/line-billing-bot:<sha|latest>
                           ghcr.io/<owner>/line-billing-backoffice-web:<sha|latest>
                                         │ docker compose pull
                                         ▼
server:  nginx ภายนอก ──line-router-net──▶ billing-test-bot (:8500) ──▶ central-db / database line_billing_test
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
- อยากให้โหลดไฟล์ใหม่ทันที: `docker compose restart billing-test-bot`

---

## 4. สร้าง `.env`

ทั้ง `billing-test-bot`, `db` และ `backoffice-api` อ่านไฟล์เดียวกันนี้

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

# --- DB ของบอท: database line_billing_test บน central-db (ข้อ 4.1) ---
DATABASE_URL=postgresql+asyncpg://line_billing_test:<รหัสผ่านของ role>@central-db:5432/line_billing_test

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
| `DATABASE_URL` | ✅ | host ต้องเป็น `central-db` **ห้ามใช้ `db`** เพราะใน `line-router-net` ชื่อ `db` ชี้ได้ทั้ง central-db และ `line-platform-db` ของ production |
| `BACKOFFICE_SECRET` | ✅ | ใช้ sign cookie ถ้าสั้นกว่า 32 ตัว backoffice จะไม่เปิด สร้างด้วย `openssl rand -hex 32` |
| `BACKOFFICE_COOKIE_SECURE` | | `true` เมื่อเข้า backoffice ผ่าน HTTPS |
| `RICH_MENU_FONT` | | path ของฟอนต์ไทย ไม่ต้องใส่ เพราะ image ติดตั้งฟอนต์ให้แล้ว |

ค่าที่ compose ตั้งให้เอง ไม่ต้องใส่ใน `.env`: `ATTACHMENT_DIR`, `DATABASE_HOST`,
`EMPLOYEE_DB_ENV_FILE` และ `TEST_TEXT_COMMANDS_ENABLED`

```bash
chmod 600 .env
```

### 4.1 Database บน central-db (ทำครั้งเดียว)

บอทใช้ database `line_billing_test` ของ role `line_billing_test` บน central-db
(ไม่ใช่ superuser จำกัด connection ไว้ 10 และ role อื่นเข้าไม่ได้) ดูและจัดการได้จาก pgAdmin (`central-db-ui`)

```bash
umask 077; openssl rand -hex 24 > .line_billing_test_db_password
docker exec -i central-db psql -U central -d postgres -v ON_ERROR_STOP=1 -v pw="$(cat .line_billing_test_db_password)" <<'SQL'
CREATE ROLE line_billing_test LOGIN PASSWORD :'pw' NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10;
CREATE DATABASE line_billing_test OWNER line_billing_test;
REVOKE ALL ON DATABASE line_billing_test FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE line_billing_test TO line_billing_test;
SQL
```

database ว่างได้เลย ตอนบอทเปิด migration จะสร้างตารางให้ ห้ามสร้างตารางของบอทไว้ใน database `central`

`backoffice-api` ต่อ central-db ผ่าน network `db_default` (มีแค่ central-db กับ pgAdmin)
ไม่ผ่าน `line-router-net` เพราะ backoffice ของ production ใช้ชื่อ `backoffice-api` อยู่ในนั้นแล้ว

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
docker compose ps          # billing-test-bot, db, backoffice-api, backoffice-web ต้องเป็น running / healthy
docker compose logs -f billing-test-bot
```

ตอน `billing-test-bot` เปิด จะรัน `alembic upgrade head` ก่อนเสมอ ถ้า DB ว่าง migration จะสร้างทุกตารางให้
ถ้า migration ล้ม container จะหยุด (ดูสาเหตุได้จาก `docker compose logs billing-test-bot`)

service ชื่อ `billing-test-bot` ไม่ใช่ `app` เพราะ Docker ตั้ง alias ตามชื่อ service ให้ทุก network และ `line-oa` ของ production ใช้ alias `app` ใน `line-router-net` อยู่แล้ว ห้ามเปลี่ยนกลับเป็น `app`

ห้ามเพิ่ม `--workers` หรือ scale `billing-test-bot` เกิน 1 ตัว เพราะ session ของการส่งบิลและ lock ของผู้ใช้เก็บใน memory ของ process

---

## 7. ตั้ง nginx ภายนอก

route อยู่บน `nginx-cloudflare` (`/opt/nginx-cloudflare`) มันตัด prefix ด้วย `rewrite`
แล้วส่งต่อไปที่ **ชื่อ container** `line-billing-test-bot` ซึ่ง compose ล็อกไว้ด้วย `container_name`
ถ้าจะเปลี่ยนชื่อนี้ ต้องแก้ทั้ง compose และ nginx และต้องเปิด container ชื่อใหม่ก่อนค่อย reload nginx

```nginx
location ^~ /line-oa-test {
    rewrite ^/line-oa-test/+(.+)$ /$1 break;
    proxy_pass http://line-billing-test-bot:8500;
    ...
}
```

⚠️ nginx แปลงชื่อ container เป็น IP ครั้งเดียวตอนเปิดหรือ reload เท่านั้น:
- ถ้า container ของบอทถูกสร้างใหม่แล้วได้ IP ใหม่ `/line-oa-test` จะตอบ 502 ให้ reload nginx
  (`docker exec nginx-cloudflare nginx -s reload` เป็นการ reload แบบไม่ตัด connection production ยังใช้งานได้ตลอด)
- **ห้าม restart nginx-cloudflare ตอนที่บอท test ปิดอยู่** nginx จะหาชื่อ `line-billing-test-bot` ไม่เจอ แล้วเปิดไม่ขึ้นเลย ทุก route รวมถึง production จะล่มไปด้วย
  (ถ้าวันหน้าจะแก้ ให้ใส่ `resolver 127.0.0.11` แล้วใช้ upstream เป็นตัวแปรแทน ซึ่งต้องแก้ config ส่วนกลาง ควรตกลงกับผู้ดูแล nginx ก่อน)

| URL ภายนอก | ไปที่ |
|---|---|
| `https://<domain>/line-oa-test/callback` | webhook ของ LINE |
| `https://<domain>/line-oa-test/api/liff/...` | API ที่ LIFF เรียก |
| `https://<domain>/line-oa-test/assets/...` | โลโก้ที่ส่งตอนลงทะเบียน |
| `https://<domain>/line-oa-test/health` | ตรวจว่าบอทเปิดอยู่ |

Backoffice เปิดให้เครื่องใน LAN เข้าที่ `http://<IP ของ server>:18510` (แบบเดียวกับ backoffice production ที่ `:8510`)
ไม่ผ่าน nginx และป้องกันด้วยการ login ของ backoffice อย่างเดียว ถ้าจะเปิดออก internet ผ่าน nginx
ให้จำกัด IP และตั้ง `BACKOFFICE_COOKIE_SECURE=true` ส่วนการจัดการ DB โดยตรงใช้ pgAdmin (`central-db-ui`)

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
docker compose logs billing-test-bot | grep -E "Running upgrade|ERROR"
```

- กด Verify webhook ใน Console ต้องขึ้น Success
- ทักบอทใน LINE ต้องได้ข้อความให้ลงทะเบียน
- ดูเวลาที่ LIFF ใช้: `docker compose logs billing-test-bot | grep "LIFF customer"` (มี `verify_ms`, `employee_ms`, `total_ms`)

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

## 12. ประวัติการย้าย (ทำไปแล้ว 2026-10-15)

- เลิกใช้แบบ mount `./app` กับ `--reload` และเอา Redis ออก โค้ดเก่าบน server ย้ายไปไว้ที่ `_old_code_20261015/`
- DB test เดิม (container `db` และ volume `line-billing-test-postgres-data`) migrate เป็น `a8c4e6f0b2d3` แล้ว
  `pg_dump` ไปไว้ที่ `_backup_20261015/line_platform_test.dump` และ restore เข้า `line_billing_test` บน central-db
  ทุกตารางมีจำนวนแถวตรงกัน
- volume เดิมยังเก็บไว้สำหรับ rollback ถ้าใช้งานไปสักพักแล้วไม่มีปัญหา ลบได้ด้วย `docker volume rm line-billing-test-postgres-data`
- container บอทเปลี่ยนชื่อเป็น `line-billing-test-bot` และ nginx ชี้ไปที่ชื่อนี้แล้ว

---

## 13. ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / แก้ |
|---|---|
| `set BOT_IMAGE` ตอน `up` | ยังไม่ได้ใส่ `BOT_IMAGE` / `BACKOFFICE_WEB_IMAGE` ใน `.env` |
| `pull access denied` / `unauthorized` | ยังไม่ได้ login GHCR หรือ token ไม่มีสิทธิ์ `read:packages` หรือ `<owner>` เป็นตัวใหญ่ |
| `network line-router-net declared as external, but could not be found` | stack ของ central-db ยังไม่ได้รัน หรือ network ชื่อไม่ตรง |
| `POSTGRES_PASSWORD is not set in /run/secrets/central-db.env` | วางโฟลเดอร์ deploy ไม่ได้อยู่ข้าง `db/` หรือ `../db/.env` ไม่มีค่านี้ |
| `billing-test-bot` restart วน และ log มี `alembic` error | migration ล้ม ดูข้อ 12.1 |
| `BACKOFFICE_SECRET must be set to at least 32 random characters` | `BACKOFFICE_SECRET` สั้นเกิน |
| LIFF ได้ 404 `Not Found` ทุก path | nginx ไม่ได้ตัด prefix (ไม่มี `rewrite` ใน route) หรือ image ยังเป็นตัวเก่า |
| `/line-oa-test` ตอบ 502 หลัง deploy | container ได้ IP ใหม่ แต่ nginx ยังจำ IP เดิมอยู่: `docker exec nginx-cloudflare nginx -s reload` |
| LIFF ยืนยันผ่าน แต่ไม่มีหน้าอัปโหลดรูปในแชต | LIFF กับ Messaging API อยู่คนละ provider (ข้อ 8) |
| รายชื่อลูกค้าว่าง | ไม่มีไฟล์ใน `data/validated/output/` หรือรหัสพนักงานไม่อยู่ใน `group_latest.json` |
| โลโก้ตอนลงทะเบียนไม่ขึ้น | `PUBLIC_BASE_URL` ผิด หรือไม่ได้รวม prefix `/line-oa-test` |
