"""会议关联分析 Celery 任务。

定时任务（Celery Beat）：
- 全量关联分析：每 3 天跑一次，分析所有已转录会议

手动触发：
- 前端会议列表页"分析关联"按钮 → 调用 /meetings/relations/analyze
- 通过 task_notification.delay(task_id) 也能间接触发

分析结果会写入 meeting_relations 表，供前端图谱展示使用。
"""

import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# 复用 meeting_workflow 中的进程池桥接器
_LoopProxy = None


def _get_loop_proxy():
    """懒加载 _LoopProxy（避免循环 import）"""
    global _LoopProxy
    if _LoopProxy is None:
        from app.agents.meeting_workflow import _LoopProxy as LP

        _LoopProxy = LP
    return _LoopProxy


@celery_app.task(name="app.tasks.relation_analysis.run_global_relation_analysis", bind=True)
def run_global_relation_analysis(self) -> dict:
    """
    Celery 任务：全局关联分析（每 3 天定时触发，或管理员手动触发）。

    分析所有 status=transcribed/processed 的会议，调用 LLM 识别关联关系，
    结果写入 meeting_relations 表。

    Returns:
        {
            "meetings_analyzed": int,
            "relations_created": int,
            "errors": list[str],
        }
    """
    try:
        proxy = _get_loop_proxy()
        result = proxy.run_in_process_pool(
            "analyze_relations",
            _need_session=True,
        )
    except Exception as exc:
        logger.error("全局关联分析任务失败: %s", exc, exc_info=True)
        return {
            "meetings_analyzed": 0,
            "relations_created": 0,
            "errors": [str(exc)],
        }

    return result


@celery_app.task(name="app.tasks.relation_analysis.analyze_single_meeting_relations")
def analyze_single_meeting_relations(meeting_id: int) -> dict:
    """
    单会议关联分析：分析指定会议与其他已有会议之间的关联。

    当新会议转写完成后调用，分析该会议与历史会议的关系。
    注意：这是轻量分析，只分析 1 vs N（该会议 vs 所有已转录会议），
    不做全局两两分析。

    Returns:
        {
            "meeting_id": int,
            "relations_created": int,
            "errors": list[str],
        }
    """
    try:
        proxy = _get_loop_proxy()
        result = proxy.run_in_process_pool(
            "analyze_relations",
            meeting_ids=[meeting_id],
            _need_session=True,
        )
        # 统一返回格式
        if isinstance(result, dict) and "meeting_id" not in result:
            result["meeting_id"] = meeting_id
    except Exception as exc:
        logger.error("单会议 %d 关联分析失败: %s", meeting_id, exc, exc_info=True)
        return {"meeting_id": meeting_id, "relations_created": 0, "errors": [str(exc)]}

    return result
