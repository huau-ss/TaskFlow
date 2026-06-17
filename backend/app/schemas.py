from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import MeetingStatus, TaskStatus


# Auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Employee
class EmployeeBase(BaseModel):
    name: str
    email: EmailStr
    manager_id: int | None = None


class EmployeeCreate(EmployeeBase):
    password: str = Field(min_length=6)


class EmployeeUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    manager_id: int | None = None
    is_active: bool | None = None


class EmployeeResponse(EmployeeBase):
    id: int
    is_active: bool
    is_admin: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeWithManager(EmployeeResponse):
    manager: EmployeeResponse | None = None


# Meeting
class MeetingResponse(BaseModel):
    id: int
    title: str | None
    nas_path: str
    original_filename: str | None
    file_size: int | None
    status: MeetingStatus
    asr_error: str | None
    creator_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptSegmentResponse(BaseModel):
    id: int
    speaker_label: str
    employee_id: int | None = None  # 识别出的员工 ID
    text: str
    start_time: float | None
    end_time: float | None
    sequence: int

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    meeting_id: int
    status: MeetingStatus
    segments: list[TranscriptSegmentResponse]


# Task
class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    deadline: datetime | None
    status: TaskStatus
    executor_id: int | None
    meeting_id: int | None
    source_segment_ids: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskExtractResponse(BaseModel):
    meeting_id: int
    tasks_created: int
    tasks: list[TaskResponse]


class HealthResponse(BaseModel):
    status: str
    asr_diarize_url: str
    llm_url: str


# VoicePrint / 声纹识别
class VoicePrintBase(BaseModel):
    note: str | None = None


class VoicePrintCreate(VoicePrintBase):
    employee_id: int
    embedding: list[float]  # 声纹特征向量
    source_audio_path: str | None = None
    audio_duration: float | None = None


class VoicePrintResponse(VoicePrintBase):
    id: int
    employee_id: int
    embedding: str  # 存储时为 JSON 字符串
    source_audio_path: str | None
    audio_duration: float | None
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VoicePrintListItem(VoicePrintBase):
    """列表用的轻量 schema，不含 embedding 大字段"""
    id: int
    employee_id: int
    source_audio_path: str | None
    audio_duration: float | None
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VoicePrintBase64Request(BaseModel):
    employee_id: int
    audio_base64: str
    note: str | None = None


class VoicePrintVerifyRequest(BaseModel):
    employee_id: int
    audio_data: str | None = None  # Base64 编码的音频数据
    audio_path: str | None = None  # 或者音频文件路径


class SpeakerRecognitionResult(BaseModel):
    """说话人识别结果"""
    speaker_label: str
    recognized_employee_id: int | None
    employee_name: str | None
    confidence: float  # 置信度 0-1


class TranscriptSegmentWithSpeaker(BaseModel):
    """带说话人信息的音频片段"""
    id: int
    speaker_label: str
    employee_id: int | None
    employee_name: str | None
    text: str
    start_time: float | None
    end_time: float | None
    sequence: int
    confidence: float | None  # 声纹匹配置信度

    model_config = {"from_attributes": True}


class TranscriptWithSpeakers(BaseModel):
    """带说话人识别的完整转写"""
    meeting_id: int
    status: MeetingStatus
    segments: list[TranscriptSegmentWithSpeaker]
