"""Admin: unbind an employee from their LINE account.

    uv run --no-sync python -m app.identity.release <EMP_CODE> <ADMIN_NAME>

ADMIN_NAME goes into the audit log as who released it.

The LINE account drops back to the "ลงทะเบียน" menu, and the employee must
register again (code + name) from the LINE account they want to use.
"""

import asyncio
import sys

from app.identity import directory, repository
from app.line import api as line_api
from app.line import richmenu


async def main(emp_code: str, admin: str) -> int:
    emp_code = directory.normalize_code(emp_code)
    line_user_id = await repository.release_line_identity(emp_code, admin=admin)

    if line_user_id is None:
        print(f"ไม่พบการผูก LINE ของรหัส {emp_code}")
        return 1

    try:
        await richmenu.unlink(line_user_id)
    finally:
        await line_api.close()

    print(f"ปลดรหัส {emp_code} ออกจาก LINE {line_user_id} แล้ว ให้พนักงานลงทะเบียนใหม่")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
