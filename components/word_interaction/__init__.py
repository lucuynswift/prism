# ============================================================
# 新文件：components/word_interaction/__init__.py
# 功能：声明一个双向 Streamlit 组件，承载依存句法面板的左右键交互
# 替代原 generate_interactive_sentence_html 的纯展示版本
# ============================================================
import streamlit.components.v1 as components
import os

# 💡 确保你在定义组件时，使用的是服务器上的绝对路径，指向你刚才放 index.html 的 build 目录
_RELEASE = True

if not _RELEASE:
    _component_func = components.declare_component(
        "word_interaction",
        url="http://localhost:3001",
    )
else:
    # 🌟 核心修改点：显式指向服务器存放 build 静态资源的绝对路径
    absolute_build_path = "/opt/prism/app/components/word_interaction/frontend/build"

    _component_func = components.declare_component(
        "word_interaction",
        path=absolute_build_path
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