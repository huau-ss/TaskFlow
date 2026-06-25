import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskStatus(str, enum.Enum):
    pending = "pending"  # 待处理（初始状态）
    accepted = "accepted"  # 已接受
    rejected = "rejected"  # 已拒绝
    in_progress = "in_progress"  # 进行中
    completed = "completed"  # 已完成
    incomplete = "incomplete"  # 未完成（需说明理由）
    overdue = "overdue"  # 已逾期
    escalated = "escalated"  # 已升级


class MessageType(str, enum.Enum):
    task_created = "task_created"  # 任务创建通知
    task_reminder = "task_reminder"  # 任务到期提醒
    task_escalation = "task_escalation"  # 任务升级通知
    task_response = "task_response"  # 任务回复通知（接受/拒绝/完成等）


class MeetingStatus(str, enum.Enum):
    uploaded = "uploaded"
    transcribing = "transcribing"
    transcribed = "transcribed"
    failed = "failed"


class RelationType(str, enum.Enum):
    follow_up = "follow_up"  # 后续会议（同一议题的延续）
    related = "related"       # 相关会议（同项目/同客户）
    prerequisite = "prerequisite"  # 前置会议（需先完成前者）


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    manager: Mapped["Employee | None"] = relationship("Employee", remote_side=[id], back_populates="subordinates")
    subordinates: Mapped[list["Employee"]] = relationship("Employee", back_populates="manager")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="executor")
    meetings: Mapped[list["Meeting"]] = relationship("Meeting", back_populates="creator")
    voice_prints: Mapped[list["VoicePrint"]] = relationship("VoicePrint", back_populates="employee")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship("TranscriptSegment", back_populates="employee")
    sent_messages: Mapped[list["Message"]] = relationship("Message", foreign_keys="[Message.sender_id]", back_populates="sender")
    received_messages: Mapped[list["Message"]] = relationship("Message", foreign_keys="[Message.recipient_id]", back_populates="recipient")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nas_path: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status"), default=MeetingStatus.uploaded
    )
    asr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimized_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM 优化后的转写文本
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    creator: Mapped["Employee | None"] = relationship("Employee", back_populates="meetings")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        "TranscriptSegment", back_populates="meeting", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="meeting")
    # 关联到我作为 A 方的会议关系
    relations_as_a: Mapped[list["MeetingRelation"]] = relationship(
        "MeetingRelation", foreign_keys="MeetingRelation.meeting_a_id", back_populates="meeting_a"
    )
    # 关联到我作为 B 方的会议关系
    relations_as_b: Mapped[list["MeetingRelation"]] = relationship(
        "MeetingRelation", foreign_keys="MeetingRelation.meeting_b_id", back_populates="meeting_b"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False, index=True)
    speaker_label: Mapped[str] = mapped_column(String(50), nullable=False)
    # 识别出的员工 ID（如果识别成功）
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float | None] = mapped_column(nullable=True)
    end_time: Mapped[float | None] = mapped_column(nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="segments")
    employee: Mapped["Employee | None"] = relationship("Employee", back_populates="transcript_segments")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), default=TaskStatus.pending)
    executor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    source_segment_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 执行人匹配方式: "voiceprint" / "name_exact" / "name_fuzzy" / null
    match_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 匹配置信度 (0.0–1.0)，声纹为 cosine similarity，姓名为 1.0
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    executor: Mapped["Employee | None"] = relationship("Employee", back_populates="tasks")
    meeting: Mapped["Meeting | None"] = relationship("Meeting", back_populates="tasks")
    updates: Mapped[list["TaskUpdate"]] = relationship("TaskUpdate", back_populates="task")


class TaskUpdate(Base):
    __tablename__ = "task_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["Task"] = relationship("Task", back_populates="updates")


class PermissionRule(Base):
    __tablename__ = "permission_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    executor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    escalation_manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    skip_direct_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_escalate: Mapped[bool] = mapped_column(Boolean, default=True)


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoicePrint(Base):
    """声纹特征数据，关联到员工"""
    __tablename__ = "voice_prints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    # 声纹特征向量（通常是一个 embedding，由 ASR 服务返回）
    # 存储为 JSON 数组格式的字符串
    embedding: Mapped[str] = mapped_column(Text, nullable=False)
    # 声纹来源的音频片段路径（方便后续重新提取）
    source_audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 音频时长（秒）
    audio_duration: Mapped[float | None] = mapped_column(nullable=True)
    # 是否为验证通过的声纹
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # 备注
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 声纹模型版本，用于区分不同 embedding 向量空间（mfcc-v1: 256-d MFCC, ecapa-tdnn: 192-d CAM++）
    # 注意：mfcc-v1 和 ecapa-tdnn 不在同一向量空间，识别时必须按此字段过滤
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ecapa-tdnn")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    employee: Mapped["Employee"] = relationship("Employee", back_populates="voice_prints")


class Message(Base):
    """App 内消息表"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[MessageType] = mapped_column(Enum(MessageType, name="message_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    action_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["Task | None"] = relationship("Task")
    sender: Mapped["Employee | None"] = relationship("Employee", foreign_keys=[sender_id])
    recipient: Mapped["Employee"] = relationship("Employee", foreign_keys=[recipient_id])
    actions: Mapped[list["MessageAction"]] = relationship("MessageAction", back_populates="message", cascade="all, delete-orphan")


class MessageAction(Base):
    """消息操作记录"""
    __tablename__ = "message_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # accept, reject, complete, incomplete
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship("Message", back_populates="actions")


class MeetingRelation(Base):
    """
    会议关联关系表。
    - meeting_a → meeting_b 表示 A 和 B 有关联。
    - direction 由 relation_type 决定语义：
        - follow_up: A 是前序，B 是后续
        - related:  A 和 B 同属一个项目/客户，无方向
        - prerequisite: A 是前置，B 依赖 A 的结果
    """
    __tablename__ = "meeting_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_a_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False, index=True)
    meeting_b_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), nullable=False, index=True)
    relation_type: Mapped[RelationType] = mapped_column(
        Enum(RelationType, name="relation_type"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0–1.0
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM 给出的关联理由
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    meeting_a: Mapped["Meeting"] = relationship(
        "Meeting", foreign_keys=[meeting_a_id], back_populates="relations_as_a"
    )
    meeting_b: Mapped["Meeting"] = relationship(
        "Meeting", foreign_keys=[meeting_b_id], back_populates="relations_as_b"
    )
