#!/usr/bin/env python3
"""Verify connectivity to ASR and LLM services."""

import asyncio
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402


async def check_asr_diarize() -> bool:
    url = settings.asr_diarize_url
    print(f"Checking ASR diarization: {url}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url.rsplit("/api", 1)[0] + "/health")
            if resp.status_code == 200:
                print(f"  OK: {resp.text[:200]}")
                return True
            print(f"  WARN: status {resp.status_code}, endpoint may differ")
            return resp.status_code < 500
    except httpx.ConnectError:
        print("  FAIL: cannot connect (service may be offline or unreachable)")
        return False
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


async def check_llm() -> bool:
    url = f"{settings.llm_url.rstrip('/')}/models"
    print(f"Checking LLM: {url}")
    headers = {}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                print(f"  OK: models available")
                return True
            print(f"  WARN: status {resp.status_code}")
            return resp.status_code < 500
    except httpx.ConnectError:
        print("  FAIL: cannot connect (service may be offline or unreachable)")
        return False
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


async def check_backend() -> bool:
    base = os.getenv("BACKEND_URL", "http://localhost:8000")
    url = f"{base}/health"
    print(f"Checking backend: {url}")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            data = resp.json()
            print(f"  OK: {data}")
            return data.get("status") == "ok"
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


async def main() -> int:
    print("=== Connectivity Verification ===\n")
    results = await asyncio.gather(
        check_asr_diarize(),
        check_llm(),
        check_backend(),
    )
    print()
    if all(results):
        print("All checks passed.")
        return 0
    print("Some checks failed (expected if services are not on network).")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
