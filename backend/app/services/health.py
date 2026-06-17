import httpx

from app.config import settings


async def check_asr_health() -> dict:
    base = settings.asr_diarize_url.rsplit("/api", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/health")
            return {"reachable": True, "status_code": resp.status_code}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


async def check_llm_health() -> dict:
    url = f"{settings.llm_url.rstrip('/')}/models"
    headers = {}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            return {"reachable": True, "status_code": resp.status_code}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}
