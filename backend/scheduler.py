"""每日定时任务 — 自动跑留存扫描

用 APScheduler 每天早上定时扫描一次；如果没装 APScheduler，
降级为「不自动跑」，手动接口 POST /api/retention/scan 照常可用。
"""

from loguru import logger

from backend.database.connection import SessionLocal
from backend.database.retention import RetentionService

# 每天几点扫描（本地时间）。放早上 8 点，发型师开工前清单就备好了。
SCAN_HOUR = 8
SCAN_MINUTE = 30

_scheduler = None


def _run_daily_scan():
    """定时任务实体：开一个独立 session 跑扫描"""
    db = SessionLocal()
    try:
        RetentionService.scan_and_generate(db)
    except Exception as e:
        logger.error(f"❌ 定时留存扫描失败: {e}")
    finally:
        db.close()


def start_scheduler():
    """启动定时任务。装了 APScheduler 才生效，否则安静降级。"""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "⚠️ 未安装 APScheduler，每日留存扫描不会自动运行。"
            "可手动调用 POST /api/retention/scan，或 pip install apscheduler 后重启。"
        )
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_daily_scan,
        trigger=CronTrigger(hour=SCAN_HOUR, minute=SCAN_MINUTE),
        id="daily_retention_scan",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"⏰ 留存定时扫描已启动，每天 {SCAN_HOUR:02d}:{SCAN_MINUTE:02d} 运行")


def shutdown_scheduler():
    """关闭定时任务"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("⏰ 留存定时扫描已停止")
