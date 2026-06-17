"""
声纹识别服务：负责声纹注册、特征提取和说话人识别

工作流程：
1. 注册声纹：上传员工音频 -> 提取声纹特征 -> 存储到数据库
2. 识别说话人：会议音频 -> ASR 提取声纹和文本 -> 比对已有声纹 -> 返回识别结果
"""

import json
import logging
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Employee, TranscriptSegment, VoicePrint

logger = logging.getLogger(__name__)


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


class VoicePrintService:
    """声纹识别服务"""
    
    # 声纹匹配置信度阈值
    SPEAKER_SIMILARITY_THRESHOLD = 0.7  # 余弦相似度阈值，高于此值认为是同一人
    MIN_SAMPLES_THRESHOLD = 0.5  # 最低置信度阈值
    
    def __init__(self, db: Session):
        self.db = db
    
    async def extract_voice_embedding(self, audio_path: Path) -> list[float] | None:
        """
        调用 ASR 服务提取声纹特征向量

        ASR 服务需要返回 embedding 数据，格式示例：
        {
            "embedding": [0.123, -0.456, ...],  # 512维或1024维向量
            "duration": 5.2
        }
        """
        import aiofiles

        embedding_url = getattr(settings, "embedding_url", "http://localhost:8003")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with aiofiles.open(audio_path, "rb") as f:
                    audio_data = await f.read()
                files = {"file": (audio_path.name, audio_data, "audio/wav")}
                resp = await client.post(
                    f"{embedding_url}/api/embeddings",
                    files=files
                )
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embedding")
                if embedding and isinstance(embedding, list):
                    return embedding
                logger.warning(f"Embedding 服务返回格式不正确: {data}")
                return None
        except Exception as e:
            logger.error(f"声纹特征提取失败: {e}")
            return None
    
    def register_voice_print(
        self,
        employee_id: int,
        embedding: list[float],
        source_audio_path: str | None = None,
        audio_duration: float | None = None,
        note: str | None = None,
        is_verified: bool = False
    ) -> VoicePrint:
        """
        注册员工声纹

        Args:
            employee_id: 员工 ID
            embedding: 声纹特征向量
            source_audio_path: 来源音频路径
            audio_duration: 音频时长
            note: 备注
            is_verified: 是否已验证
        """
        voice_print = VoicePrint(
            employee_id=employee_id,
            embedding=json.dumps(embedding),
            source_audio_path=source_audio_path,
            audio_duration=audio_duration,
            note=note,
            is_verified=is_verified
        )
        self.db.add(voice_print)
        return voice_print
    
    def get_employee_voice_prints(self, employee_id: int) -> list[VoicePrint]:
        """获取员工的所有声纹"""
        result = self.db.execute(
            select(VoicePrint)
            .where(VoicePrint.employee_id == employee_id)
            .order_by(VoicePrint.created_at.desc())
        )
        return list(result.scalars().all())
    
    def get_all_verified_embeddings(self) -> dict[int, list[list[float]]]:
        """
        获取所有已验证员工的声纹特征向量
        
        Returns:
            { employee_id: [embedding1, embedding2, ...] }
        """
        result = self.db.execute(
            select(VoicePrint)
            .where(VoicePrint.is_verified == True)
        )
        voice_prints = result.scalars().all()
        
        embeddings_map: dict[int, list[list[float]]] = {}
        for vp in voice_prints:
            if vp.employee_id not in embeddings_map:
                embeddings_map[vp.employee_id] = []
            try:
                embedding = json.loads(vp.embedding)
                if isinstance(embedding, list):
                    embeddings_map[vp.employee_id].append(embedding)
            except json.JSONDecodeError:
                logger.warning(f"无法解析声纹 embedding: {vp.id}")
        
        return embeddings_map
    
    def recognize_speaker(
        self,
        embedding: list[float]
    ) -> tuple[int | None, float]:
        """
        识别说话人
        
        Args:
            embedding: 待识别的声纹特征向量
            
        Returns:
            (recognized_employee_id, confidence) 如果找不到匹配返回 (None, 0)
        """
        all_embeddings = self.get_all_verified_embeddings()
        
        if not all_embeddings:
            logger.info("没有已注册的声纹，无法识别说话人")
            return None, 0.0
        
        best_match_employee_id: int | None = None
        best_similarity = 0.0
        
        for employee_id, embeddings in all_embeddings.items():
            # 对该员工的所有声纹取平均
            avg_embedding = np.mean(embeddings, axis=0).tolist()
            similarity = cosine_similarity(embedding, avg_embedding)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_employee_id = employee_id
        
        # 如果相似度低于阈值，认为无法识别
        if best_similarity < self.SPEAKER_SIMILARITY_THRESHOLD:
            logger.info(f"声纹匹配置信度 {best_similarity} 低于阈值 {self.SPEAKER_SIMILARITY_THRESHOLD}，无法识别")
            return None, best_similarity
        
        logger.info(f"识别说话人: employee_id={best_match_employee_id}, 置信度={best_similarity:.3f}")
        return best_match_employee_id, best_similarity
    
    def recognize_all_speakers_in_meeting(
        self,
        segments_with_embeddings: list[dict]
    ) -> list[dict]:
        """
        识别会议中所有说话人
        
        Args:
            segments_with_embeddings: [{"speaker_label": str, "embedding": list[float], ...}]
            
        Returns:
            [{"speaker_label": str, "employee_id": int|None, "confidence": float, ...}]
        """
        all_embeddings = self.get_all_verified_embeddings()
        
        if not all_embeddings:
            logger.info("没有已注册的声纹，返回原始标签")
            return segments_with_embeddings
        
        results = []
        for seg in segments_with_embeddings:
            embedding = seg.get("embedding", [])
            if not embedding:
                results.append({
                    **seg,
                    "employee_id": None,
                    "confidence": 0.0
                })
                continue
            
            employee_id, confidence = self.recognize_speaker(embedding)
            results.append({
                **seg,
                "employee_id": employee_id,
                "confidence": confidence
            })
        
        return results


# 同步版本，用于 Celery 任务
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import sessionmaker as _sessionmaker

_sync_engine = _create_engine(settings.database_url_sync)
_SyncSession = _sessionmaker(_sync_engine)


class SyncVoicePrintService:
    """同步版声纹服务，用于 Celery 任务"""

    def __init__(self):
        self.Session = _SyncSession
    
    def get_employee_voice_prints(self, employee_id: int) -> list[VoicePrint]:
        with self.Session() as db:
            result = db.execute(
                select(VoicePrint)
                .where(VoicePrint.employee_id == employee_id)
                .order_by(VoicePrint.created_at.desc())
            )
            return list(result.scalars().all())
    
    def get_all_verified_embeddings(self) -> dict[int, list[list[float]]]:
        with self.Session() as db:
            result = db.execute(
                select(VoicePrint)
                .where(VoicePrint.is_verified == True)
            )
            voice_prints = result.scalars().all()
            
            embeddings_map: dict[int, list[list[float]]] = {}
            for vp in voice_prints:
                if vp.employee_id not in embeddings_map:
                    embeddings_map[vp.employee_id] = []
                try:
                    embedding = json.loads(vp.embedding)
                    if isinstance(embedding, list):
                        embeddings_map[vp.employee_id].append(embedding)
                except json.JSONDecodeError:
                    pass
            
            return embeddings_map
