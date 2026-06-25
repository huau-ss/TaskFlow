import json
import logging
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Meeting, MeetingStatus, TranscriptSegment
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

sync_engine = create_engine(settings.database_url_sync)
SyncSession = sessionmaker(sync_engine)


def _parse_asr_response(data: dict | list) -> list[dict]:
    """Normalize ASR API response into segment dicts."""
    segments: list[dict] = []

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                segments.append(
                    {
                        "speaker_label": str(item.get("speaker", item.get("speaker_label", f"SPEAKER_{i}"))),
                        "text": item.get("text", item.get("transcript", "")),
                        "start_time": item.get("start", item.get("start_time")),
                        "end_time": item.get("end", item.get("end_time")),
                        "embedding": item.get("embedding"),  # 声纹特征向量（如果有）
                        "sequence": i,
                    }
                )
        return segments

    if isinstance(data, dict):
        if "segments" in data:
            raw = data["segments"]
        elif "utterances" in data:
            raw = data["utterances"]
        elif "results" in data:
            raw = data["results"]
        else:
            text = data.get("text", data.get("transcript", ""))
            if text:
                segments.append(
                    {
                        "speaker_label": "SPEAKER_0",
                        "text": text,
                        "start_time": None,
                        "end_time": None,
                        "embedding": None,
                        "sequence": 0,
                    }
                )
            return segments

        for i, item in enumerate(raw):
            segments.append(
                {
                    "speaker_label": str(item.get("speaker", item.get("speaker_label", f"SPEAKER_{i}"))),
                    "text": item.get("text", item.get("transcript", "")),
                    "start_time": item.get("start", item.get("start_time")),
                    "end_time": item.get("end", item.get("end_time")),
                    "embedding": item.get("embedding"),  # 声纹特征向量
                    "sequence": i,
                }
            )
    return segments


def _mock_transcript_segments() -> list[dict]:
    return [
        {
            "speaker_label": "SPEAKER_0",
            "text": "李明，请在下周三之前完成用户调研报告。",
            "start_time": 0.0,
            "end_time": 5.0,
            "embedding": None,
            "sequence": 0,
        },
        {
            "speaker_label": "SPEAKER_1",
            "text": "王芳负责整理会议纪要，本周五前发给张经理。",
            "start_time": 5.0,
            "end_time": 10.0,
            "embedding": None,
            "sequence": 1,
        },
    ]


# ============== Plan A: pyannote diarization preprocessing ==============


def _call_funasr_transcribe(audio_path: Path) -> dict:
    """调用 FunASR 统一转写服务：VAD + ASR + CAM++ embedding + 说话人聚类。

    一次 HTTP 调用替换旧的 8004(pyannote) + 8002(ASR) + 8003(MFCC) 三步骤。
    """
    funasr_url = getattr(settings, "funasr_url", "http://localhost:8005")
    with httpx.Client(timeout=600.0) as client:
        with open(audio_path, "rb") as f:
            resp = client.post(
                f"{funasr_url}/api/transcribe",
                files={"file": (audio_path.name, f, "audio/wav")},
            )
        resp.raise_for_status()
        return resp.json()


def _get_audio_duration(audio_path: Path) -> float | None:
    """用 ffprobe 获取音频时长（秒），失败返回 None。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        return None
    except Exception:
        return None


def _call_diarization_api(audio_path: Path) -> dict | None:
    """
    调用 pyannote 说话人分离服务 (8004)，获取精准的说话人边界。

    返回：
        {
            "segments": [{"speaker": "SPEAKER_00", "start": 0.5, "end": 12.3}, ...],
            "num_speakers": 2,
            "duration": 60.0
        }
    失败时返回 None（调用方应回退到 8002 联合模式）。
    """
    try:
        with httpx.Client(timeout=600.0) as client:
            with open(audio_path, "rb") as f:
                resp = client.post(
                    f"{settings.diarization_url}/api/diarize",
                    files={"file": (audio_path.name, f, "audio/wav")},
                    timeout=600.0,
                )
            resp.raise_for_status()
            result = resp.json()
            if result.get("segments"):
                return result
            logger.warning("Diarization 返回空 segments，回退到 8002 联合模式")
            return None
    except Exception as e:
        logger.warning(f"Diarization 服务不可用 ({e})，回退到 8002 联合模式")
        return None


def _slice_audio(audio_path: Path, start: float, end: float) -> Path:
    """
    用 ffmpeg 从音频中截取指定时间段的片段。

    Args:
        audio_path: 原始音频路径
        start: 开始时间（秒）
        end: 结束时间（秒）

    Returns:
        截取后的 16kHz mono WAV 文件路径
    """
    duration = max(end - start, 0.5)  # 最短 0.5 秒
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", str(audio_path),
            "-ar", "16000", "-ac", "1", "-f", "wav",
            tmp_path,
        ],
        capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        Path(tmp_path).unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg slice failed: {result.stderr.decode()}")

    return Path(tmp_path)


def _call_asr_transcribe(audio_path: Path) -> tuple[str, list[float] | None]:
    """
    对单个音频片段调用 8002 ASR 转写，返回 (文本, 声纹embedding)。

    与 _call_asr_api 不同，此函数专用于短音频片段（pyannote 切分后的单个说话人段落）。
    同时从 8002 响应中提取 CAM++ embedding（与注册声纹同空间），避免后续调 8003。

    支持 8002 的同步和异步两种模式。
    """
    if settings.mock_asr:
        return ("[Mock] 模拟转写文本", None)

    def _extract_text_and_embedding(data: dict | list) -> tuple[str, list[float] | None]:
        """从 ASR 响应中同时提取文本和 embedding"""
        segments = _parse_asr_response(data)
        text = " ".join(s["text"] for s in segments if s["text"].strip())
        # 提取首个有效的 embedding（8002 CAM++ 格式）
        for s in segments:
            emb = s.get("embedding")
            if emb and isinstance(emb, list) and len(emb) > 0:
                return (text, emb)
        return (text, None)

    with httpx.Client(timeout=600.0) as client:
        with open(audio_path, "rb") as f:
            resp = client.post(
                settings.asr_diarize_url,
                files={"env_audio": (audio_path.name, f, "audio/wav")},
            )
        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception:
            # 可能是纯文本或 Markdown 返回（无 embedding）
            md_text = resp.text
            parsed = _parse_markdown_transcript(md_text)
            text, _ = _extract_text_and_embedding(parsed)
            return (text or md_text.strip(), None)

        # 同步模式：直接返回了 segments/utterances/results/text
        if "segments" in data or "utterances" in data or "results" in data or "text" in data:
            return _extract_text_and_embedding(data)

        # 异步模式：轮询等待结果
        task_id = data.get("task_id")
        if not task_id:
            return _extract_text_and_embedding(data)

        base_url = settings.asr_diarize_url.rsplit("/api", 1)[0]
        for _ in range(200):  # 最多等待 ~10 分钟
            time.sleep(3)
            status_resp = client.get(f"{base_url}/api/status/{task_id}")
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "failed":
                raise Exception(f"ASR 失败: {status_data.get('error', 'unknown')}")

            if status in ("done", "completed"):
                result_resp = client.get(f"{base_url}/api/result/{task_id}")
                result_resp.raise_for_status()

                try:
                    result_data = result_resp.json()
                    return _extract_text_and_embedding(result_data)
                except Exception:
                    md_text = result_resp.text
                    parsed = _parse_markdown_transcript(md_text)
                    text, _ = _extract_text_and_embedding(parsed)
                    return (text or md_text.strip(), None)

        raise Exception("ASR 转写超时")


def _transcribe_segments_parallel(audio_path: Path, diar_segments: list[dict]) -> list[dict]:
    """
    对 pyannote 分割的每个说话人段落，并行执行 ASR 转写。

    Args:
        audio_path: 原始音频文件路径
        diar_segments: pyannote 返回的 segments 列表

    Returns:
        带有 text 的完整 segment 列表（与 _parse_asr_response 输出格式兼容）
    """
    n = len(diar_segments)
    logger.info(f"并行转写 {n} 个说话人段落（最多 4 路并发）...")

    results: list[dict | None] = [None] * n

    def process_one(idx: int, seg: dict) -> tuple[int, dict]:
        sliced_path = None
        try:
            sliced_path = _slice_audio(audio_path, seg["start"], seg["end"])
            text, embedding = _call_asr_transcribe(sliced_path)
            return idx, {
                "speaker_label": seg["speaker"],
                "text": text,
                "start_time": seg["start"],
                "end_time": seg["end"],
                "embedding": embedding,  # 8002 CAM++ embedding（与注册声纹同空间）
                "sequence": idx,
            }
        except Exception as e:
            logger.warning(f"段落 {idx} ({seg['speaker']}, {seg['start']:.1f}s–{seg['end']:.1f}s) ASR 失败: {e}")
            return idx, {
                "speaker_label": seg["speaker"],
                "text": "",
                "start_time": seg["start"],
                "end_time": seg["end"],
                "embedding": None,
                "sequence": idx,
            }
        finally:
            if sliced_path:
                try:
                    sliced_path.unlink(missing_ok=True)
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(process_one, i, seg): i
            for i, seg in enumerate(diar_segments)
        }
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    # 过滤掉 None 和文本为空的段落
    filtered = [r for r in results if r is not None]
    none_count = sum(1 for r in results if r is None)
    if none_count:
        logger.warning(f"{none_count}/{n} 个段落的转写结果丢失（future 未完成）")
    logger.info(f"并行转写完成: {sum(1 for r in filtered if r['text'].strip())}/{n} 个段落有有效文本")
    return filtered


# ============== 原有 ASR 调用（回退路径） ==============


def _call_asr_api(audio_path: Path) -> dict | list:
    if settings.mock_asr:
        return {"segments": _mock_transcript_segments()}

    with httpx.Client(timeout=600.0) as client:
        # 上传音频到 ASR 服务
        with open(audio_path, "rb") as f:
            resp = client.post(
                settings.asr_diarize_url,
                files={"env_audio": (audio_path.name, f, "audio/wav")},
            )
        resp.raise_for_status()
        data = resp.json()

        # 如果直接返回 segments（同步模式），直接返回
        if "segments" in data or "utterances" in data or "results" in data:
            return data

        # 异步模式：轮询等待结果
        task_id = data.get("task_id")
        if not task_id:
            return data

        base_url = settings.asr_diarize_url.rsplit("/api", 1)[0]
        for _ in range(200):  # 最多等待 ~10 分钟
            time.sleep(3)
            status_resp = client.get(f"{base_url}/api/status/{task_id}")
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "failed":
                error = status_data.get("error", "ASR 处理失败")
                raise Exception(f"ASR 失败: {error}")

            if status in ("done", "completed"):
                # 获取结果
                result_resp = client.get(f"{base_url}/api/result/{task_id}")
                result_resp.raise_for_status()

                # 尝试 JSON 解析
                try:
                    result_data = result_resp.json()
                    if isinstance(result_data, (dict, list)):
                        return result_data
                except Exception:
                    pass

                # Markdown 格式解析
                md_text = result_resp.text
                return _parse_markdown_transcript(md_text)

        raise Exception("ASR 处理超时")


def _parse_markdown_transcript(md_text: str) -> dict:
    """解析 8002 返回的 Markdown 格式转写文本"""

    segments = []
    # 匹配 [HH:MM:SS] 或 [MM:SS] + **说话人 X**：内容
    pattern = r'\[(\d{1,2}:?\d{2}:\d{2})\]\s*\*\*(.+?)\*\*[：:]\s*(.+?)(?=\n\[|\Z)'
    matches = re.findall(pattern, md_text, re.DOTALL)

    for i, (timestamp, speaker, text) in enumerate(matches):
        # 解析时间戳为秒数
        parts = timestamp.split(":")
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + int(parts[1])
        else:
            seconds = 0

        segments.append({
            "speaker_label": speaker.strip(),
            "text": text.strip(),
            "start_time": float(seconds),
            "end_time": None,
            "embedding": None,
            "sequence": i,
        })

    # 如果正则没匹配到，尝试按行解析
    if not segments:
        lines = md_text.strip().split("\n")
        idx = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("---"):
                continue
            # 简单匹配 **说话人** 格式
            m = re.match(r'\*\*(.+?)\*\*[：:]\s*(.+)', line)
            if m:
                segments.append({
                    "speaker_label": m.group(1).strip(),
                    "text": m.group(2).strip(),
                    "start_time": None,
                    "end_time": None,
                    "embedding": None,
                    "sequence": idx,
                })
                idx += 1

    # 如果完全无法解析，把整段文本作为一个片段
    if not segments and md_text.strip():
        segments.append({
            "speaker_label": "SPEAKER_0",
            "text": md_text.strip(),
            "start_time": None,
            "end_time": None,
            "embedding": None,
            "sequence": 0,
        })

    return {"segments": segments}


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot_product = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))


def _recognize_speaker(
    db, embedding: list[float], context: str = ""
) -> tuple[int | None, float]:
    """
    识别说话人，返回 (employee_id, confidence)

    context: 调试用的段标识，如 "seg#3 SPEAKER_01 5.2s-8.1s"
    """
    from sqlalchemy import select
    from app.models import VoicePrint

    # 获取所有已验证的声纹
    result = db.execute(
        select(VoicePrint).where(VoicePrint.is_verified == True)
    )
    voice_prints = result.scalars().all()

    if not voice_prints:
        logger.warning(f"[声纹识别] {context}: 没有已注册的声纹")
        return None, 0.0

    # 按员工分组，计算平均 embedding
    from collections import defaultdict
    employee_embeddings: dict[int, list[list[float]]] = defaultdict(list)

    for vp in voice_prints:
        try:
            emb = json.loads(vp.embedding)
            if isinstance(emb, list):
                employee_embeddings[vp.employee_id].append(emb)
        except (json.JSONDecodeError, TypeError):
            continue

    if not employee_embeddings:
        logger.warning(f"[声纹识别] {context}: 无法解析任何声纹 embedding")
        return None, 0.0

    # 逐个员工计算相似度并记录
    best_employee_id = None
    best_similarity = 0.0
    second_similarity = 0.0
    all_scores: list[tuple[int, float]] = []

    for emp_id, embeddings in employee_embeddings.items():
        avg_emb = np.mean(embeddings, axis=0).tolist()
        similarity = cosine_similarity(embedding, avg_emb)
        all_scores.append((emp_id, round(similarity, 4)))

        if similarity > best_similarity:
            second_similarity = best_similarity
            best_similarity = similarity
            best_employee_id = emp_id
        elif similarity > second_similarity:
            second_similarity = similarity

    # 日志
    scores_str = ", ".join(
        f"员工#{eid}={score:.4f}" for eid, score in all_scores
    )
    gap = best_similarity - second_similarity
    n_candidates = len(employee_embeddings)

    # 决策逻辑：
    # - 1 个候选员工：需要满足较高阈值（0.65），避免随机 embedding 误命中唯一员工
    # - 多个候选员工：双重条件——绝对分数 >= 0.3  或  gap >= 0.10（第一名拉开差距）
    if n_candidates == 1:
        # 单员工：gap 无意义（始终为 0），必须用更高阈值防止误匹配
        SINGLE_EMPLOYEE_THRESHOLD = 0.65
        matched = best_similarity >= SINGLE_EMPLOYEE_THRESHOLD
        matched_reason = f"abs={best_similarity:.4f}>={SINGLE_EMPLOYEE_THRESHOLD}"
    else:
        ABS_THRESHOLD = 0.3
        REL_GAP = 0.10
        matched = best_similarity >= ABS_THRESHOLD or gap >= REL_GAP
        matched_reason = (
            f"abs={best_similarity:.4f}>={ABS_THRESHOLD} or gap={gap:.4f}>={REL_GAP}"
        )

    if matched:
        logger.info(
            f"[声纹识别] {context}: 命中 员工#{best_employee_id} "
            f"相似度={best_similarity:.4f} gap={gap:.4f} "
            f"({matched_reason}) | 所有分数: {scores_str}"
        )
        return best_employee_id, best_similarity

    logger.info(
        f"[声纹识别] {context}: 拒绝 — "
        f"最佳 员工#{best_employee_id}={best_similarity:.4f} gap={gap:.4f} "
        f"({matched_reason}) | 所有分数: {scores_str}"
    )
    return None, best_similarity


def _extract_speaker_embedding_from_audio(
    audio_path: Path, start_time: float, end_time: float
) -> list[float] | None:
    """
    从音频中提取特定时间段的声纹特征
    
    调用 ASR 服务的 embeddings 接口
    """
    # TODO: 如果 ASR 服务支持时间范围提取，则使用；否则需要音频切片
    # 目前假设 ASR 服务可以返回每个 speaker 的 embedding
    return None


def _extract_segment_embedding(audio_path: Path, start_time: float | None, end_time: float | None) -> list[float] | None:
    """从完整音频中截取片段，调用本地 8003 embedding 服务提取 MFCC 声纹向量。

    注意：8002 只对多人会议输出 CAM++ embedding，单人切片不适用。
    改用 8003 MFCC —— 稳定且与注册同空间。
    """
    if start_time is None:
        return None

    duration = None
    if end_time is not None and end_time > start_time:
        duration = end_time - start_time
    else:
        duration = 5.0  # 默认截取 5 秒

    embedding_url = getattr(settings, "embedding_url", "http://localhost:8003")

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        # 用 ffmpeg 截取片段并转为 16kHz mono WAV
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(min(duration, 30)),  # 最长 30 秒
                "-i", str(audio_path),
                "-ar", "16000", "-ac", "1", "-f", "wav",
                tmp_path
            ],
            capture_output=True, timeout=30,
        )

        if result.returncode != 0 or not Path(tmp_path).exists():
            return None

        # 调用本地 8003 embedding 服务（MFCC 256-dim，与注册同空间）
        with open(tmp_path, "rb") as f:
            resp = httpx.post(
                f"{embedding_url}/api/embeddings",
                files={"file": ("segment.wav", f, "audio/wav")},
                timeout=30.0,
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding")

    except Exception as e:
        logger.warning(f"提取片段声纹失败: {e}")
        return None
    finally:
        if 'tmp_path' in locals():
            Path(tmp_path).unlink(missing_ok=True)


def _recognize_meeting_speakers(
    db, segments: list[dict]
) -> list[dict]:
    """
    对会议的每个片段进行说话人识别。

    策略：先按 speaker_label 聚合 CAM++ embedding（取均值），
    用聚合后的 embedding 匹配声纹，再回填到所有同 label 的 segment。

    逐段匹配噪音大（短片段 embedding 不稳定），聚合后信噪比更高。
    """
    logger.info(f"[声纹识别] 开始处理 {len(segments)} 个 segment (聚合匹配)")

    # ── Step 1: 按 speaker_label 聚合 embedding ──
    from collections import defaultdict
    speaker_embeddings: dict[str, list[list[float]]] = defaultdict(list)
    for seg in segments:
        emb = seg.get("embedding")
        if emb and isinstance(emb, list) and len(emb) > 0:
            speaker_embeddings[seg.get("speaker_label", "?")].append(emb)

    # ── Step 2: 每个说话人取平均 embedding，一次性匹配 ──
    speaker_match: dict[str, tuple[int | None, float]] = {}
    for spk, embs in speaker_embeddings.items():
        avg_emb = np.mean(embs, axis=0).tolist()
        total_dur = sum(
            (s.get("end_time") or 0) - (s.get("start_time") or 0)
            for s in segments if s.get("speaker_label") == spk
        )
        ctx = f"{spk} ({len(embs)}段, {total_dur:.1f}s)"
        employee_id, confidence = _recognize_speaker(db, avg_emb, context=ctx)
        speaker_match[spk] = (employee_id, confidence)
        logger.info(
            f"[声纹识别] {ctx}: → 员工#{employee_id} 置信度={confidence:.4f}"
        )

    # ── Step 3: 回填到每个 segment ──
    recognized_segments = []
    for seg in segments:
        spk = seg.get("speaker_label", "?")
        eid, conf = speaker_match.get(spk, (None, 0.0))
        recognized_segments.append({
            **seg,
            "employee_id": eid,
            "confidence": conf,
        })

    return recognized_segments


def run_transcribe_meeting(meeting_id: int) -> dict:
    """
    Plan A: pyannote diarization (8004) → 音频切片 → 每段 8002 ASR → 8003 embedding → 声纹匹配

    流程：
    1. 调用 pyannote (8004) 获取精准说话人边界
    2. 按 pyannote 边界用 ffmpeg 切分音频
    3. 每段分别送入 8002 ASR 转写（4 路并发）
    4. 每段送入 8003 提取声纹 embedding
    5. 声纹与员工匹配
    6. 持久化 TranscriptSegment

    如果 pyannote 不可用，自动回退到 8002 联合模式。
    """
    pipeline_mode = "unknown"
    recognized_segments: list[dict] = []
    all_segments: list[dict] = []

    # ── Phase 1: 转写 + 声纹识别 + 持久化（sync session）──
    with SyncSession() as db:
        meeting = db.get(Meeting, meeting_id)
        if not meeting:
            return {"error": "meeting not found"}

        meeting.status = MeetingStatus.transcribing
        db.commit()

        audio_path = Path(meeting.nas_path)
        if not audio_path.exists():
            meeting.status = MeetingStatus.failed
            meeting.asr_error = f"Audio file not found: {meeting.nas_path}"
            db.commit()
            return {"error": meeting.asr_error}

        try:
            # Step 1: FunASR 统一转写
            pipeline_mode = "funasr"
            logger.info(f"会议 {meeting_id}: 调用 FunASR 统一转写...")
            funasr_result = _call_funasr_transcribe(audio_path)
            all_segments = funasr_result.get("segments", [])
            logger.info(
                f"会议 {meeting_id}: FunASR 返回 {len(all_segments)} 段, "
                f"{funasr_result.get('num_speakers', '?')} 说话人"
            )
        except Exception as exc:
            meeting.status = MeetingStatus.failed
            meeting.asr_error = f"FunASR 转写失败: {exc}"
            db.commit()
            return {"error": str(exc)}

        # Step 2: 声纹识别
        recognized_segments = _recognize_meeting_speakers(
            db, all_segments
        )

        # Step 3: 持久化
        db.execute(
            delete(TranscriptSegment).where(
                TranscriptSegment.meeting_id == meeting_id
            )
        )
        for seg in recognized_segments:
            if not seg["text"].strip():
                continue
            db.add(TranscriptSegment(
                meeting_id=meeting_id,
                speaker_label=seg["speaker_label"],
                employee_id=seg.get("employee_id"),
                text=seg["text"],
                start_time=seg.get("start_time"),
                end_time=seg.get("end_time"),
                sequence=seg["sequence"],
            ))

        meeting.status = MeetingStatus.transcribed
        meeting.asr_error = None
        db.commit()

        # NAS 写入在 DB commit 之后，失败不影响已提交数据
        from app.services.transcript_segment_storage import save_segments
        saved = save_segments(
            meeting_id,
            [
                {
                    "id": seg.id,
                    "speaker_label": seg.speaker_label,
                    "employee_id": seg.employee_id,
                    "text": seg.text,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "sequence": seg.sequence,
                }
                for seg in db.query(TranscriptSegment).filter(
                    TranscriptSegment.meeting_id == meeting_id
                ).all()
            ],
        )
        if saved:
            logger.info(f"会议 {meeting_id} 转写片段已备份至 NAS: {saved}")
    # ── sync session closed here ──

    # ── Phase 2: 任务提取 + 通知（sync，无 asyncio.run 开销）──
    tasks_created = 0
    notifications_sent = 0
    errors: list[str] = []
    try:
        from app.agents.task_extract import run_task_extraction_sync
        from app.agents.task_notification import send_task_notifications_sync

        with SyncSession() as phase2_db:
            created_ids, errors = run_task_extraction_sync(phase2_db, meeting_id)
            phase2_db.commit()
            tasks_created = len(created_ids)
            notifications_sent = tasks_created  # 每个任务最多发一条通知

        if errors:
            for err in errors:
                logger.warning(f"会议 {meeting_id} Phase 2 错误: {err}")
        logger.info(
            f"会议 {meeting_id}: 提取 {tasks_created} 个任务, "
            f"发送 {notifications_sent} 条通知"
        )
    except Exception as e:
        logger.warning(f"自动任务提取/通知失败: {e}")

    return {
        "meeting_id": meeting_id,
        "pipeline_mode": pipeline_mode,
        "segments": len(all_segments),
        "recognized_speakers": sum(
            1 for s in recognized_segments if s.get("employee_id")
        ),
        "tasks_created": tasks_created,
        "notifications_sent": notifications_sent,
    }


def _is_transient_failure(result: dict) -> bool:
    """判断转写失败是否应该重试。

    OOM、HTTP 5xx、网络超时属于瞬时故障，重试有意义；
    业务错误（音频不存在、无有效语音段）重试无法解决，不重试。
    """
    if "error" not in result:
        return False
    err = result["error"].lower()

    # 资源/服务端瞬时故障 — 应该重试
    transient_keywords = [
        "oom", "out of memory", "memory error", "memoryerror",
        "connection refused", "connection reset",
        "read timeout", "timed out",
        "502", "503", "504",
        "internal server error", "bad gateway", "service unavailable",
        "killed", "signal", "core dumped",
    ]
    return any(kw in err for kw in transient_keywords)


@celery_app.task(name="transcribe_meeting", bind=True, max_retries=3)
def transcribe_meeting(self, meeting_id: int) -> dict:
    # 重试前先将状态恢复为 pending，让前端看到"正在重新处理"而非一直"失败"
    if self.request.retries > 0:
        with SyncSession() as retry_db:
            meeting = retry_db.get(Meeting, meeting_id)
            if meeting:
                meeting.status = MeetingStatus.uploaded
                retry_db.commit()

    result = run_transcribe_meeting(meeting_id)

    # 仅对瞬时故障重试；业务错误（文件不存在、音频无语音等）直接放弃
    if "error" in result:
        if _is_transient_failure(result):
            countdown = 60 + 60 * self.request.retries  # 60s → 120s → 180s
            raise self.retry(
                exc=Exception(result["error"]),
                countdown=countdown,
            )
        # 业务错误：已是最终状态，不重试
    return result
