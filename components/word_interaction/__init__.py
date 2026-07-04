import streamlit.components.v1 as components
import os

_RELEASE = True

# 路径统一：建议直接用 os.path.join 拼出来的路径，不要硬编码绝对路径
base_path = os.path.dirname(os.path.abspath(__file__))
absolute_build_path = os.path.join(base_path, "components", "word_interaction", "frontend", "build")

# 🌟 建议：名称保持原样，不要随便加 _v10，这是组件的唯一标识
_component_func = components.declare_component(
    "word_interaction",  # 保持原名称，避免注册冲突
    path=absolute_build_path
)

def word_interaction_panel(tokens, dep_map, sentence_id, key=None):
    # 此处传递参数，确保 tokens 和 dep_map 的结构与前端 JS 预期的 JSON 结构完全匹配
    return _component_func(
        tokens=tokens,
        dep_map=dep_map,
        sentence_id=sentence_id,
        key=key,
        default=None
    )

# import streamlit.components.v1 as components
# import os
#
# # 💡 强制使用 RELEASE 模式
# _RELEASE = True
#
# if not _RELEASE:
#     _component_func = components.declare_component(
#         "word_interaction",
#         url="http://localhost:3001",
#     )
# else:
#     # 🌟 核心修改点 1：显式指向服务器存放 build 静态资源的绝对路径
#     absolute_build_path = "/opt/prism/app/components/word_interaction/frontend/build"
#
#     # 🌟 核心修改点 2：这里的名字必须同步改成 "word_interaction_final_v10"！
#     # 只有这里的名字和主程序里的一致，Streamlit 才会强行抓取最新版 index.html 的颜色、字体和背景样式
#     _component_func = components.declare_component(
#         "word_interaction_final_v10",
#         path=absolute_build_path
#     )
#
# def word_interaction_panel(tokens, dep_map, sentence_id, key=None):
#     """
#     tokens: list of dict，每个词的 {lemma, display, position, deps_info}
#     dep_map: dict，position -> 依存关系信息
#     返回值: None 或 {"action": "click"|"add_wordbook", "word": {...}}
#     """
#     # 🌟 核心修改点 3：确保这里的参数传递与最新前端的接收完全一致
#     # 这样下方的依存关系展示面板才能实时拿到点击的数据，不会再显示不正确
#     return _component_func(
#         tokens=tokens,
#         dep_map=dep_map,
#         sentence_id=sentence_id,
#         key=key,
#         default=None
#     )