"""baseline = 生产提示词的引用快照。永远等于当前生产实现，作为 A/B 基线。"""
from app.services.recognition.prompt import _recognition_prompt


def build_prompt() -> str:
    return _recognition_prompt()
