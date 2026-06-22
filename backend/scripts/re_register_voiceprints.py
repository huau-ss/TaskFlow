"""
一次性脚本：把旧 MFCC 声纹全部降级为 unverified，强制在新模型下重新注册。

背景：
    8003 已从 MFCC 256-d 切换到 ECAPA-TDNN 192-d。两者不在同一向量空间，
    旧声纹不能继续用于识别，必须重新采集。

用法：
    python -m scripts.re_register_voiceprints

输出：
    - 受影响的员工列表（含 id / 姓名 / 旧声纹数量）
    - 不写文件，不删数据（保守）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import async_session
from app.models import Employee, VoicePrint


async def re_register():
    async with async_session() as db:
        vp_rows = await db.execute(
            select(VoicePrint, Employee)
            .join(Employee, VoicePrint.employee_id == Employee.id)
            .where(VoicePrint.model_version == "mfcc-v1")
        )
        rows = vp_rows.all()

        if not rows:
            print("[OK] 没有需要降级的 mfcc-v1 声纹。")
            return

        by_emp: dict[int, dict] = {}
        for vp, emp in rows:
            by_emp.setdefault(
                emp.id, {"name": emp.name, "email": emp.email, "count": 0}
            )["count"] += 1

        print(f"\n[INFO] 共 {len(rows)} 条 mfcc-v1 声纹，分布在 {len(by_emp)} 名员工：\n")
        for emp_id, info in sorted(by_emp.items()):
            print(f"  - {emp_id:>4}  {info['name']:<12} ({info['email']})  "
                  f"→ {info['count']} 条旧声纹")

        print(
            "\n将把它们全部置为 is_verified=false。"
            "管理员需要在 ECAPA-TDNN 上重新采集每个员工的声纹。"
        )
        resp = input("\n确认执行？(yes/no): ").strip().lower()
        if resp != "yes":
            print("[CANCEL] 已取消，未修改任何数据。")
            return

        for vp, _ in rows:
            vp.is_verified = False
        await db.commit()
        print(f"[OK] 已降级 {len(rows)} 条 mfcc-v1 声纹为未验证状态。")


if __name__ == "__main__":
    asyncio.run(re_register())
