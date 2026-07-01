# ============================================================
# 新文件：components/word_interaction/__init__.py
# 功能：声明一个双向 Streamlit 组件，承载依存句法面板的左右键交互
# 替代原 generate_interactive_sentence_html 的纯展示版本
# ============================================================
import streamlit.components.v1 as components
import os

_RELEASE = True  # 改成 False 可在本地用 npm run start 调试

if _RELEASE:
    _component_func = components.declare_component(
        "word_interaction",
        path=os.path.join(os.path.dirname(__file__), "frontend/build")
    )
else:
    _component_func = components.declare_component(
        "word_interaction",
        url="http://localhost:3001",
    )

def word_interaction_panel(tokens, dep_map, sentence_id, key=None):
    """
    tokens: list of dict，每个词的 {lemma, display, position, deps_info}
    dep_map: dict，position -> 依存关系信息
    返回值: None 或 {"action": "click"|"add_wordbook", "word": {...}}
    """
    return _component_func(
        tokens=tokens, dep_map=dep_map, sentence_id=sentence_id,
        key=key, default=None
    )