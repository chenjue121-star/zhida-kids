"""示例变体：在生产提示词末尾追加一条更强调厚度判断的规则。

这是模板/占位变体，证明 A/B 机制可用。真正调优时新建 variant_<name>.py，
独立编写完整提示词文本或在 baseline 基础上改写。
"""
from app.services.recognition.prompt import _recognition_prompt


def build_prompt() -> str:
    base = _recognition_prompt()
    extra = "\n5. 厚度判断务必结合面料层数与是否加绒，宁可标 normal 也不要漏判 thick/fleece。"
    return base + extra
