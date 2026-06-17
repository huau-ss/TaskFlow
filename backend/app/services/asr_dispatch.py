"""Dispatch ASR transcription via Celery, falling back to background thread."""

import logging
import threading

logger = logging.getLogger(__name__)


def dispatch_transcribe(meeting_id: int) -> None:
    """Queue transcription; use Celery when Redis is available, else a daemon thread."""
    try:
        from app.tasks.asr import transcribe_meeting

        transcribe_meeting.delay(meeting_id)
        logger.info("Queued ASR via Celery for meeting %s", meeting_id)
    except Exception as exc:
        logger.warning("Celery unavailable (%s), running ASR in background thread", exc)
        from app.tasks.asr import run_transcribe_meeting

        thread = threading.Thread(
            target=run_transcribe_meeting,
            args=(meeting_id,),
            daemon=True,
            name=f"asr-meeting-{meeting_id}",
        )
        thread.start()
