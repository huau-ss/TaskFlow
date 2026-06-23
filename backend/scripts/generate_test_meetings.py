"""生成测试会议数据（用于测试会议关联分析功能）。

场景：某科技公司"智能办公系统"项目的需求评审会议系列，共 5 个会议：

- 会议1: 智能办公系统需求评审（2024-03-01）- prerequisite → 会议2
- 会议2: 需求评审结果确认（2024-03-03）- follow_up → 会议3, related → 会议3
- 会议3: 技术方案评审（2024-03-05）- prerequisite → 会议4
- 会议4: 实施计划制定（2024-03-08）- follow_up → 会议5
- 会议5: 项目启动会（2024-03-10）

运行：
    cd backend
    python scripts/generate_test_meetings.py
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Employee, Meeting, MeetingStatus, TranscriptSegment
from app.services.transcript_segment_storage import save_segments


# ── 五个会议的转写内容 ────────────────────────────────────────────────────────

MEETINGS_DATA = [
    {
        "title": "智能办公系统需求评审",
        "date": datetime(2024, 3, 1, 14, 0),
        "nas_path": f"{settings.nas_path}/meeting_001.wav",
        "original_filename": "智能办公系统需求评审_20240301.wav",
        "speaker_labels": ["SPEAKER_0", "SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
        "participants": ["张经理", "李明", "王芳", "陈工"],
        "segments": [
            {"speaker": "SPEAKER_0", "start": 0.0, "end": 45.0,
             "text": "好，今天我们主要对智能办公系统的一期需求进行评审。李明，你先介绍一下调研结果。"},
            {"speaker": "SPEAKER_1", "start": 45.0, "end": 120.0,
             "text": "好的张经理。经过两周的调研，我们访谈了市场部、研发部、财务部共20多位同事。核心痛点有三个：一是会议纪要全靠人工整理，效率低且容易遗漏；二是跨部门任务跟踪全靠邮件和口头，信息不同步；三是周报月报占用大量管理层时间。"},
            {"speaker": "SPEAKER_2", "start": 120.0, "end": 180.0,
             "text": "王芳，你这边财务部的调研情况怎么样？"},
            {"speaker": "SPEAKER_1", "start": 180.0, "end": 240.0,
             "text": "财务部反馈最强烈的是报销流程，他们希望实现语音录入发票信息、自动识别发票类型，同时和现有的用友系统打通。"},
            {"speaker": "SPEAKER_3", "start": 240.0, "end": 300.0,
             "text": "陈工，从技术角度，这次需求有没有什么风险点？"},
            {"speaker": "SPEAKER_0", "start": 300.0, "end": 360.0,
             "text": "我比较担心语音识别的准确率，特别是财务术语和专业名词。目前市面上的ASR引擎在通用场景表现不错，但垂直领域可能需要做热词优化。另外，声纹识别区分多人的话，如果超过6个人效果会下降。"},
            {"speaker": "SPEAKER_1", "start": 360.0, "end": 420.0,
             "text": "我们可以先做一个MVP版本，只支持4个发言人以内，财务术语热词库第一期先覆盖100个高频词，后续滚动扩充。"},
            {"speaker": "SPEAKER_2", "start": 420.0, "end": 480.0,
             "text": "同意张经理的意见。这次评审后，我们输出一个最终需求文档，下周三之前确认评审结果。"},
        ],
        "expected_relations": [],  # 会议1没有前置会议
    },
    {
        "title": "需求评审结果确认",
        "date": datetime(2024, 3, 3, 10, 0),
        "nas_path": f"{settings.nas_path}/meeting_002.wav",
        "original_filename": "需求评审结果确认_20240303.wav",
        "speaker_labels": ["SPEAKER_0", "SPEAKER_1", "SPEAKER_2"],
        "participants": ["张经理", "李明", "王芳"],
        "segments": [
            {"speaker": "SPEAKER_0", "start": 0.0, "end": 60.0,
             "text": "上次评审后，需求文档V1.0已经发给大家三天了，今天我们确认一下各部门的反馈意见。"},
            {"speaker": "SPEAKER_1", "start": 60.0, "end": 150.0,
             "text": "市场部已经审阅，他们提出两个补充需求：第一，增加客户拜访记录的语音录入；第二，商机跟进任务的提醒功能。这个需要和智能办公系统做一个数据联动。"},
            {"speaker": "SPEAKER_2", "start": 150.0, "end": 210.0,
             "text": "财务部这边基本没意见，但要求报销语音录入的时间必须在6月底之前上线，因为7月开始启用新的发票认证规则。"},
            {"speaker": "SPEAKER_0", "start": 210.0, "end": 270.0,
             "text": "明白，6月底之前必须完成报销语音录入功能。那么第一期MVP的范围确认一下：会议转写加任务提取、报销语音录入、周报自动生成。技术方案讨论定在3月5号。"},
            {"speaker": "SPEAKER_1", "start": 270.0, "end": 330.0,
             "text": "李明，技术方案会上我们需要准备什么材料？"},
            {"speaker": "SPEAKER_0", "start": 330.0, "end": 390.0,
             "text": "需要陈工这边出三个技术方案的对比：本地部署ASR还是调用云端API、声纹识别引擎选型、热词库构建方案。还要和研发部确认现有系统的集成改造工作量。"},
        ],
        "expected_relations": [
            {"type": "prerequisite", "from": 1, "to": 2, "reason": "需求评审结果确认为技术方案讨论的前置依赖"}
        ],
    },
    {
        "title": "智能办公系统技术方案评审",
        "date": datetime(2024, 3, 5, 14, 0),
        "nas_path": f"{settings.nas_path}/meeting_003.wav",
        "original_filename": "技术方案评审_20240305.wav",
        "speaker_labels": ["SPEAKER_0", "SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
        "participants": ["陈工", "张经理", "李明", "王芳"],
        "segments": [
            {"speaker": "SPEAKER_0", "start": 0.0, "end": 90.0,
             "text": "根据上次的评审结果，我们对比了三个方案。方案一纯本地部署，优点是数据安全，但GPU资源投入大，初期成本高。方案二用云端API，部署快但有数据出境合规问题。方案三是混合架构，核心转写在本地，非敏感场景用云端，成本和合规兼顾。"},
            {"speaker": "SPEAKER_1", "start": 90.0, "end": 180.0,
             "text": "合规是底线，必须满足等保三级要求和公司数据安全制度。财务数据绝对不能上公有云。"},
            {"speaker": "SPEAKER_2", "start": 180.0, "end": 260.0,
             "text": "张经理，我建议用方案三，但第一期MVP阶段先用纯本地，等系统稳定后再逐步引入云端能力。这个和需求评审时定的方向是一致的。"},
            {"speaker": "SPEAKER_3", "start": 260.0, "end": 340.0,
             "text": "声纹识别我们测试了三个引擎，SpeakerText的准确率最高，达到97%，比开源的Resemblyzer高出8个百分点。价格也在预算范围内。热词库方面，第一期我们准备导入100个财务高频词和50个通用办公术语。"},
            {"speaker": "SPEAKER_0", "start": 340.0, "end": 400.0,
             "text": "好，那么技术方案确定：混合架构，声纹识别用SpeakerText，热词库第一期覆盖150个词。实施计划什么时候开始制定？"},
            {"speaker": "SPEAKER_1", "start": 400.0, "end": 460.0,
             "text": "方案确定后，下一步就是制定详细实施计划，建议3月8号开实施计划会，需要排期、确定里程碑和责任人。"},
            {"speaker": "SPEAKER_3", "start": 460.0, "end": 520.0,
             "text": "我这边粗估了一下，第一期MVP的开发周期大约需要8到10周，如果3月中旬启动，6月中旬可以交付报销语音录入功能的Beta版本。"},
        ],
        "expected_relations": [
            {"type": "prerequisite", "from": 2, "to": 3, "reason": "技术方案评审是实施计划制定的前置"}
        ],
    },
    {
        "title": "智能办公系统实施计划制定",
        "date": datetime(2024, 3, 8, 14, 0),
        "nas_path": f"{settings.nas_path}/meeting_004.wav",
        "original_filename": "实施计划制定_20240308.wav",
        "speaker_labels": ["SPEAKER_0", "SPEAKER_1", "SPEAKER_2"],
        "participants": ["张经理", "李明", "陈工"],
        "segments": [
            {"speaker": "SPEAKER_0", "start": 0.0, "end": 75.0,
             "text": "技术方案上周已经评审通过，今天我们来制定详细实施计划。根据陈工的时间评估，第一期MVP是8到10周，我们定10周，留2周缓冲。"},
            {"speaker": "SPEAKER_1", "start": 75.0, "end": 150.0,
             "text": "整个计划分四个阶段：第1到第2周是需求细化和接口设计；第3到第6周是核心功能开发，包括ASR集成、声纹识别、会议转写存储；第7到第8周是报销语音录入和周报生成功能；第9到第10周是联调测试和上线准备。"},
            {"speaker": "SPEAKER_2", "start": 150.0, "end": 230.0,
             "text": "关于里程碑：第6周末出Alpha版本，支持会议转写基础功能；第8周末出Beta版本，包含报销语音录入；第10周上线。这个和财务部要求的6月底报销功能是一致的。"},
            {"speaker": "SPEAKER_0", "start": 230.0, "end": 290.0,
             "text": "好，责任人和资源分配确认一下：前端和集成由李明负责，后端AI能力由陈工负责，产品和测试由王芳协调。3月11号（下周一）正式kick off项目。"},
            {"speaker": "SPEAKER_1", "start": 290.0, "end": 360.0,
             "text": "张经理，启动会需要邀请哪些人？需要我准备PPT吗？"},
            {"speaker": "SPEAKER_0", "start": 360.0, "end": 420.0,
             "text": "启动会参加人员：管理层的张经理、我、研发总负责人陈工、市场部李明、财务部代表。PPT需要准备，主要讲项目背景、目标、团队和里程碑。另外，确认一下采购服务器的时间，ASR本地部署需要两台GPU服务器。"},
            {"speaker": "SPEAKER_2", "start": 420.0, "end": 480.0,
             "text": "服务器采购流程大约需要2到3周，建议3月15号之前完成下单，这样不影响第3周的开发进度。启动会的具体时间你们定，我这边安排好手上的另一个项目后全力投入。"},
        ],
        "expected_relations": [
            {"type": "follow_up", "from": 3, "to": 4, "reason": "实施计划制定会议是项目启动会的延续，确认了具体执行方案后需要正式Kick Off"}
        ],
    },
    {
        "title": "智能办公系统项目启动会",
        "date": datetime(2024, 3, 10, 10, 0),
        "nas_path": f"{settings.nas_path}/meeting_005.wav",
        "original_filename": "项目启动会_20240310.wav",
        "speaker_labels": ["SPEAKER_0", "SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
        "participants": ["张经理", "陈工", "李明", "王芳"],
        "segments": [
            {"speaker": "SPEAKER_0", "start": 0.0, "end": 90.0,
             "text": "欢迎大家参加智能办公系统项目启动会。这个项目是公司今年数字化转型的重点工程，目标是在6月底之前交付报销语音录入的MVP，9月底完成第一期全部功能。上周的需求评审、技术方案、实施计划都已经确认完毕，今天正式Kick Off。"},
            {"speaker": "SPEAKER_1", "start": 90.0, "end": 180.0,
             "text": "我来介绍一下项目目标：三个核心功能——第一，会议智能转写并自动提取任务；第二，报销发票语音录入；第三，管理层周报自动生成。第一期MVP聚焦会议转写和报销录入，满足财务部6月底的时间要求。"},
            {"speaker": "SPEAKER_2", "start": 180.0, "end": 260.0,
             "text": "团队分工确认：后端AI能力由我负责，包括ASR引擎集成、声纹识别、热词库管理；前端和现有系统集成由李明负责；王芳负责产品设计和测试协调。"},
            {"speaker": "SPEAKER_3", "start": 260.0, "end": 340.0,
             "text": "里程碑再强调一下：第6周末Alpha版本（会议转写基础功能），第8周末Beta版本（包含报销录入），第10周正式上线。财务部要求的6月底报销功能在Beta版本里就能交付。"},
            {"speaker": "SPEAKER_0", "start": 340.0, "end": 400.0,
             "text": "好，今天启动会之后，所有人全力投入。这个项目关系到下半年的绩效考核，希望大家重视。有什么问题和困难随时在项目群里沟通。"},
            {"speaker": "SPEAKER_1", "start": 400.0, "end": 460.0,
             "text": "张经理，我这边有个情况想同步一下——GPU服务器还在走采购流程，预计3月15号才能到货。这两周开发环境先用云端ASR做联调，本地部署等服务器到位再切换。"},
            {"speaker": "SPEAKER_2", "start": 460.0, "end": 520.0,
             "text": "明白，云端联调没问题，但数据安全这边需要提前和金总确认一下，看财务数据的测试样本是否可以直接用云端处理。王芳，协调一下这个确认。"},
            {"speaker": "SPEAKER_3", "start": 520.0, "end": 580.0,
             "text": "好的，我明天就找金总确认。另外，关于用户培训计划，等系统上线后需要安排两轮培训，第一轮是管理层，第二轮是市场部和财务部的关键用户。"},
        ],
        "expected_relations": [],
    },
]


async def generate_test_meetings():
    """创建5个测试会议及其转写片段。"""
    async with async_session() as db:
        # 确保至少有一个员工
        result = await db.execute(select(Employee).limit(1))
        employee = result.scalar_one_or_none()
        if not employee:
            print("错误：数据库中没有任何员工，请先运行 seed.py")
            return

        existing = await db.execute(select(Meeting).limit(1))
        if existing.scalar_one_or_none():
            print("警告：数据库中已有会议数据，继续生成测试会议...")

        created = []
        for i, data in enumerate(MEETINGS_DATA):
            # 创建会议记录
            meeting = Meeting(
                title=data["title"],
                nas_path=data["nas_path"],
                original_filename=data["original_filename"],
                file_size=1024 * 1024 * 10,  # 10MB 假数据
                status=MeetingStatus.transcribed,
                creator_id=employee.id,
                created_at=data["date"],
            )
            db.add(meeting)
            await db.flush()

            # 创建转写片段
            segments = []
            for seq, seg_data in enumerate(data["segments"]):
                seg = TranscriptSegment(
                    meeting_id=meeting.id,
                    speaker_label=seg_data["speaker"],
                    text=seg_data["text"],
                    start_time=seg_data["start"],
                    end_time=seg_data["end"],
                    sequence=seq,
                )
                db.add(seg)
                segments.append(seg)

            await db.flush()

            # 写入 NAS JSON（模拟真实写入）
            await save_segments(db, meeting.id, segments)

            created.append(meeting)
            print(f"  创建会议 [{meeting.id}] {data['title']} ({len(segments)} 个片段)")

        await db.commit()
        print(f"\n成功创建 {len(created)} 个测试会议。")

        # 打印预期的关联关系
        print("\n预期关联关系：")
        for data in MEETINGS_DATA:
            for rel in data.get("expected_relations", []):
                print(f"  会议{rel['from']} → [{rel['type']}] → 会议{rel['to']}: {rel['reason']}")

        print("\n会议ID对应关系：")
        for m in created:
            print(f"  会议{m.id}: {m.title}")


if __name__ == "__main__":
    print("开始生成测试会议数据...\n")
    asyncio.run(generate_test_meetings())
    print("\n完成！可以在系统中测试会议关联分析功能。")
