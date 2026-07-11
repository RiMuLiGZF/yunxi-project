"""情绪陪伴模式 API"""
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import random

router = APIRouter()

# ========== 内存数据 ==========

# 情绪记录
_emotion_records = []
for i in range(30):
    d = datetime.now() - timedelta(days=29 - i)
    emotions = ["happy", "calm", "neutral", "anxious", "sad", "angry"]
    weights = [3, 3, 2, 1, 1, 0.5]
    emo = random.choices(emotions, weights=weights, k=1)[0]
    _emotion_records.append({
        "id": i + 1,
        "emotion": emo,
        "level": random.randint(3, 9),
        "trigger": random.choice(["工作压力", "人际关系", "健康状况", "天气", "睡眠", "运动", "阅读", "美食"]),
        "note": "",
        "date": d.strftime("%Y-%m-%d"),
        "created_at": d.isoformat(),
    })

# 放松引导
_relaxations = [
    {"id": 1, "title": "478 呼吸法", "duration": "5分钟", "type": "breathing", "description": "吸气4秒，屏息7秒，呼气8秒，快速平复情绪", "steps": ["找一个舒适的姿势坐下", "用鼻子吸气4秒", "屏息7秒", "用嘴呼气8秒", "重复5-10次"]},
    {"id": 2, "title": "渐进式肌肉放松", "duration": "10分钟", "type": "muscle", "description": "从头到脚逐组肌肉紧张放松，释放身体压力", "steps": ["握紧拳头5秒然后放松", "手臂紧张5秒然后放松", "肩膀向上提5秒然后放松", "脸部表情紧张5秒然后放松", "全身放松感受平静"]},
    {"id": 3, "title": "正念冥想", "duration": "15分钟", "type": "meditation", "description": "专注呼吸，观察思绪，不评判不抗拒", "steps": ["闭眼坐好，脊柱挺直", "注意力放在呼吸上", "思绪飘走时轻轻拉回", "感受身体的感觉", "慢慢睁开眼睛"]},
    {"id": 4, "title": "身体扫描", "duration": "12分钟", "type": "body_scan", "description": "从头到脚逐一感受身体各部位，释放紧张", "steps": ["平躺或舒适坐下", "从头顶开始扫描", "感受每个部位的感觉", "发现紧张就深呼吸放松", "完成后感受全身"]},
    {"id": 5, "title": "箱式呼吸", "duration": "4分钟", "type": "breathing", "description": "吸4-屏4-呼4-屏4，像画一个正方形", "steps": ["吸气4秒", "屏息4秒", "呼气4秒", "屏息4秒", "重复循环"]},
]

# 助眠内容
_sleep_contents = [
    {"id": 1, "title": "海浪声助眠", "duration": "30分钟", "type": "nature", "description": "舒缓的海浪声，带你进入深度睡眠"},
    {"id": 2, "title": "雨声白噪音", "duration": "45分钟", "type": "rain", "description": "轻柔的雨声，安神助眠好帮手"},
    {"id": 3, "title": "睡前故事：星空旅行", "duration": "20分钟", "type": "story", "description": "温暖的睡前故事，伴随你入眠"},
    {"id": 4, "title": "深度睡眠冥想", "duration": "25分钟", "type": "meditation", "description": "引导式冥想，快速进入深度睡眠状态"},
    {"id": 5, "title": "森林鸟鸣", "duration": "35分钟", "type": "nature", "description": "清晨森林的声音，自然疗愈"},
]

# 心理测评
_assessments = [
    {
        "id": 1,
        "title": "压力水平测评",
        "description": "评估当前的心理压力水平",
        "type": "stress",
        "questions_count": 10,
        "duration": "5分钟",
        "questions": [
            {"id": 1, "text": "最近经常感到紧张或焦虑", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 2, "text": "睡眠质量下降，难以入睡", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 3, "text": "容易感到疲惫，精力不足", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 4, "text": "注意力难以集中", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 5, "text": "容易烦躁或发脾气", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 6, "text": "感到事情失去控制", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 7, "text": "肌肉紧张或头痛", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 8, "text": "食欲变化明显", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 9, "text": "对事情失去兴趣", "options": ["从不", "偶尔", "经常", "总是"]},
            {"id": 10, "text": "感到孤独或无助", "options": ["从不", "偶尔", "经常", "总是"]},
        ],
    },
    {
        "id": 2,
        "title": "情绪状态测评",
        "description": "了解自己的情绪健康状况",
        "type": "emotion",
        "questions_count": 8,
        "duration": "4分钟",
        "questions": [
            {"id": 1, "text": "大部分时间感到愉快", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 2, "text": "能够很好地调节情绪", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 3, "text": "对未来充满希望", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 4, "text": "遇到挫折能快速恢复", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 5, "text": "经常感到焦虑或担忧", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 6, "text": "容易感到悲伤或低落", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 7, "text": "对自己感到满意", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
            {"id": 8, "text": "生活中有很多让我开心的事", "options": ["完全不符合", "不太符合", "比较符合", "非常符合"]},
        ],
    },
    {
        "id": 3,
        "title": "睡眠质量测评",
        "description": "评估你的睡眠质量",
        "type": "sleep",
        "questions_count": 7,
        "duration": "3分钟",
        "questions": [
            {"id": 1, "text": "入睡时间（关灯到睡着）", "options": ["15分钟内", "16-30分钟", "31-60分钟", "60分钟以上"]},
            {"id": 2, "text": "夜间醒来次数", "options": ["0次", "1-2次", "3-4次", "5次以上"]},
            {"id": 3, "text": "总睡眠时间", "options": ["7-9小时", "6-7小时", "5-6小时", "5小时以下"]},
            {"id": 4, "text": "早上起床后的精神状态", "options": ["精力充沛", "还可以", "有点累", "非常疲惫"]},
            {"id": 5, "text": "白天困倦程度", "options": ["完全不困", "偶尔犯困", "经常犯困", "总是很困"]},
            {"id": 6, "text": "睡眠规律性", "options": ["非常规律", "比较规律", "不太规律", "完全不规律"]},
            {"id": 7, "text": "对睡眠质量的满意度", "options": ["非常满意", "比较满意", "不太满意", "很不满意"]},
        ],
    },
]

# 测评结果
_assessment_results = [
    {"id": 1, "assessment_id": 1, "title": "压力水平测评", "result": "轻度压力", "score": 28, "level": "normal", "date": "2026-07-01", "suggestion": "你的压力水平处于正常范围，继续保持良好的生活习惯。"},
    {"id": 2, "assessment_id": 2, "title": "情绪状态测评", "result": "情绪状态良好", "score": 25, "level": "good", "date": "2026-06-25", "suggestion": "你的情绪状态良好，保持积极乐观的心态。"},
]

# 心情日记
_mood_entries = [
    {"id": 1, "emotion": "happy", "content": "今天完成了一个重要项目，很有成就感。和朋友一起吃了好吃的，聊得很开心。", "date": "2026-07-05", "tags": ["工作", "朋友"]},
    {"id": 2, "emotion": "calm", "content": "平静的一天，读了一本好书，喝了一杯茶。", "date": "2026-07-04", "tags": ["阅读", "放松"]},
    {"id": 3, "emotion": "anxious", "content": "下周有个重要的汇报，有点紧张。准备了很久但还是担心不够好。", "date": "2026-07-03", "tags": ["工作", "焦虑"]},
    {"id": 4, "emotion": "sad", "content": "和好朋友吵架了，心里很难受。不知道该不该主动联系。", "date": "2026-07-02", "tags": ["人际关系", "难过"]},
    {"id": 5, "emotion": "happy", "content": "运动后心情特别好，全身都舒畅了。", "date": "2026-07-01", "tags": ["运动", "开心"]},
]


# ========== 请求模型 ==========
class EmotionRecordRequest(BaseModel):
    emotion: str
    level: int
    trigger: str = ""
    note: str = ""


class AssessmentSubmitRequest(BaseModel):
    assessment_id: int
    answers: dict  # { question_id: option_index }


class MoodEntryRequest(BaseModel):
    emotion: str
    content: str
    tags: List[str] = []


# ========== 概览 ==========
@router.get("/overview")
async def get_overview():
    """情绪陪伴概览"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_record = next((r for r in _emotion_records if r["date"] == today), None)
    
    # 情绪统计
    emotion_counts = {}
    for r in _emotion_records[-7:]:
        emotion_counts[r["emotion"]] = emotion_counts.get(r["emotion"], 0) + 1
    dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "calm"
    
    avg_level = sum(r["level"] for r in _emotion_records[-7:]) / max(len(_emotion_records[-7:]), 1)
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "stats": {
                "total_records": len(_emotion_records),
                "streak_days": 25,
                "dominant_emotion": dominant,
                "avg_level": round(avg_level, 1),
                "today_recorded": today_record is not None,
                "today_emotion": today_record["emotion"] if today_record else None,
            },
            "current_mood": today_record,
        },
    }


# ========== 情绪记录 ==========
@router.get("/emotions")
async def get_emotions(days: int = 30):
    """获取情绪记录"""
    records = _emotion_records[-days:]
    return {"code": 0, "message": "ok", "data": records}


@router.get("/emotions/stats")
async def get_emotion_stats(days: int = 30):
    """情绪统计"""
    records = _emotion_records[-days:]
    
    # 分布
    distribution = {}
    for r in records:
        distribution[r["emotion"]] = distribution.get(r["emotion"], 0) + 1
    
    # 日趋势
    daily = []
    for r in records:
        daily.append({
            "date": r["date"],
            "emotion": r["emotion"],
            "level": r["level"],
        })
    
    # 触发因素统计
    triggers = {}
    for r in records:
        if r["trigger"]:
            triggers[r["trigger"]] = triggers.get(r["trigger"], 0) + 1
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total_records": len(records),
            "distribution": distribution,
            "daily_trend": daily,
            "triggers": triggers,
            "dominant_emotion": max(distribution, key=distribution.get) if distribution else "calm",
        },
    }


@router.post("/emotions")
async def record_emotion(req: EmotionRecordRequest):
    """记录情绪"""
    rid = max((r["id"] for r in _emotion_records), default=0) + 1
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 如果今天已有记录，更新
    existing = next((r for r in _emotion_records if r["date"] == today), None)
    if existing:
        existing["emotion"] = req.emotion
        existing["level"] = req.level
        existing["trigger"] = req.trigger
        existing["note"] = req.note
        return {"code": 0, "message": "今日情绪已更新", "data": existing}
    
    record = {
        "id": rid,
        "emotion": req.emotion,
        "level": req.level,
        "trigger": req.trigger,
        "note": req.note,
        "date": today,
        "created_at": datetime.now().isoformat(),
    }
    _emotion_records.append(record)
    return {"code": 0, "message": "情绪记录成功", "data": record}


# ========== 放松引导 ==========
@router.get("/relaxations")
async def get_relaxations(rtype: Optional[str] = None):
    """获取放松引导列表"""
    items = _relaxations
    if rtype:
        items = [r for r in items if r["type"] == rtype]
    return {"code": 0, "message": "ok", "data": items}


@router.get("/relaxations/{rid}")
async def get_relaxation_detail(rid: int):
    """获取放松引导详情"""
    item = next((r for r in _relaxations if r["id"] == rid), None)
    if not item:
        return {"code": 404, "message": "内容不存在", "data": None}
    return {"code": 0, "message": "ok", "data": item}


# ========== 助眠内容 ==========
@router.get("/sleep")
async def get_sleep_contents(stype: Optional[str] = None):
    """获取助眠内容列表"""
    items = _sleep_contents
    if stype:
        items = [s for s in items if s["type"] == stype]
    return {"code": 0, "message": "ok", "data": items}


# ========== 心理测评 ==========
@router.get("/assessments")
async def get_assessments():
    """获取测评列表"""
    # 不返回完整题目
    simple = [{"id": a["id"], "title": a["title"], "description": a["description"],
               "type": a["type"], "questions_count": a["questions_count"],
               "duration": a["duration"]} for a in _assessments]
    return {"code": 0, "message": "ok", "data": simple}


@router.get("/assessments/results")
async def get_assessment_results():
    """获取测评历史"""
    return {"code": 0, "message": "ok", "data": _assessment_results}


@router.get("/assessments/{aid}")
async def get_assessment_detail(aid: int):
    """获取测评详情（含题目）"""
    assessment = next((a for a in _assessments if a["id"] == aid), None)
    if not assessment:
        return {"code": 404, "message": "测评不存在", "data": None}
    return {"code": 0, "message": "ok", "data": assessment}


@router.post("/assessments/submit")
async def submit_assessment(req: AssessmentSubmitRequest):
    """提交测评"""
    assessment = next((a for a in _assessments if a["id"] == req.assessment_id), None)
    if not assessment:
        return {"code": 404, "message": "测评不存在", "data": None}
    
    # 计算分数
    total_score = sum(v for v in req.answers.values() if isinstance(v, int))
    max_score = len(assessment["questions"]) * 3
    percentage = total_score / max_score * 100
    
    if assessment["type"] == "stress":
        if percentage < 30:
            result_text = "压力水平很低"
            level = "low"
            suggestion = "你的压力水平很低，继续保持轻松愉快的生活状态。"
        elif percentage < 60:
            result_text = "轻度压力"
            level = "normal"
            suggestion = "你的压力处于正常范围，注意劳逸结合，适当放松。"
        elif percentage < 80:
            result_text = "中度压力"
            level = "moderate"
            suggestion = "你承受着中度压力，建议增加放松练习，必要时寻求支持。"
        else:
            result_text = "高度压力"
            level = "high"
            suggestion = "你的压力水平较高，建议寻求专业帮助。"
    elif assessment["type"] == "emotion":
        if percentage > 70:
            result_text = "情绪状态优秀"
            level = "excellent"
            suggestion = "你的情绪状态非常好，继续保持积极心态！"
        elif percentage > 50:
            result_text = "情绪状态良好"
            level = "good"
            suggestion = "你的情绪状态良好，保持乐观积极的生活态度。"
        elif percentage > 30:
            result_text = "情绪一般"
            level = "normal"
            suggestion = "情绪有些波动是正常的，试着多关注自己的情绪需求。"
        else:
            result_text = "情绪较低落"
            level = "low"
            suggestion = "近期情绪较低落，建议多和朋友交流，必要时寻求帮助。"
    else:  # sleep
        if percentage > 70:
            result_text = "睡眠质量优秀"
            level = "excellent"
            suggestion = "你的睡眠质量非常好，继续保持良好的作息习惯。"
        elif percentage > 50:
            result_text = "睡眠质量良好"
            level = "good"
            suggestion = "睡眠质量还不错，可以进一步优化作息。"
        elif percentage > 30:
            result_text = "睡眠质量一般"
            level = "normal"
            suggestion = "睡眠质量有待提高，建议调整作息规律。"
        else:
            result_text = "睡眠质量较差"
            level = "poor"
            suggestion = "睡眠质量较差，建议改善睡眠环境和作息。"
    
    result = {
        "id": len(_assessment_results) + 1,
        "assessment_id": req.assessment_id,
        "title": assessment["title"],
        "result": result_text,
        "score": total_score,
        "level": level,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "suggestion": suggestion,
    }
    _assessment_results.append(result)
    
    return {"code": 0, "message": "测评完成", "data": result}


# ========== 心情日记 ==========
@router.get("/mood-entries")
async def get_mood_entries(emotion: Optional[str] = None):
    """获取心情日记"""
    entries = _mood_entries
    if emotion:
        entries = [e for e in entries if e["emotion"] == emotion]
    return {"code": 0, "message": "ok", "data": entries}


@router.post("/mood-entries")
async def create_mood_entry(req: MoodEntryRequest):
    """创建心情日记"""
    eid = max((e["id"] for e in _mood_entries), default=0) + 1
    entry = {
        "id": eid,
        "emotion": req.emotion,
        "content": req.content,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tags": req.tags,
    }
    _mood_entries.insert(0, entry)
    return {"code": 0, "message": "日记保存成功", "data": entry}
