"""Create or reset a backoffice account.

    uv run --no-sync python -m backoffice.api.create_admin <username> [admin|viewer]

Asks for the password (not echoed). Running it again for an existing username
resets that account's password and role and re-enables it.
"""

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db.models.admin_user import AdminUser
from app.db.session import SessionLocal
from backoffice.api.auth import hash_password

MIN_PASSWORD = 10


async def main(username: str, role: str) -> int:
    username = username.strip().lower()

    if role not in ("admin", "viewer") or not username:
        print(__doc__)
        return 2

    password = getpass.getpass("รหัสผ่าน: ")
    if len(password) < MIN_PASSWORD:
        print(f"รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD} ตัวอักษร")
        return 1
    if password != getpass.getpass("ยืนยันรหัสผ่าน: "):
        print("รหัสผ่านไม่ตรงกัน")
        return 1

    async with SessionLocal() as session:
        admin = await session.scalar(select(AdminUser).where(AdminUser.username == username))

        if admin is None:
            session.add(AdminUser(username=username, password_hash=hash_password(password), role=role, active=True))
            action = "สร้าง"
        else:
            admin.password_hash, admin.role, admin.active = hash_password(password), role, True
            action = "รีเซ็ต"

        await session.commit()

    print(f"{action}บัญชี {username} ({role}) แล้ว")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else "admin")))
