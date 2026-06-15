# 文件位置：本地 prism-main/book_registry.py
# 推送到：GitHub prism-main 仓库
# 运行在：Streamlit Cloud

# ══════════════════════════════════════════
# ★ 每次新增书籍只需修改这一个文件
# ★ 需要填写的地方已用注释标出
# ══════════════════════════════════════════

BOOK_REGISTRY = {
# ── 免费书（用于吸引新用户）──────────────────────────────
    "Ulysses — James Joyce": {
        # ★ slug：唯一标识符，用于存储进度，只能用字母数字下划线
        "slug": "Ulysses",

        # ★ repo：填你的 GitHub 用户名和仓库名
        # 格式固定为：
        # https://raw.githubusercontent.com/你的用户名/仓库名/main
        "repo": "https://raw.githubusercontent.com/lucuynswift/prism-data-Ulysses/main",

        "description": "Leopold Bloom's ordinary day in Dublin, reimagining Homer's Odyssey through stream of consciousness..",
        "free": True,   # True = 免费用户可读
    },
# ── 付费书 ──────────────────────────────────────────────
    "The Great Gatsby — F. Scott Fitzgerald": {
        # ★ slug：唯一标识符，用于存储进度，只能用字母数字下划线
        "slug": "great_gatsby",

        # ★ repo：填你的 GitHub 用户名和仓库名
        # 格式固定为：
        # https://raw.githubusercontent.com/你的用户名/仓库名/main
        "repo": "https://raw.githubusercontent.com/lucuynswift/prism-data-great-gatsby/main",

        "description": "A story of wealth, love, and the American Dream.",
        "free": False,   # True = 免费用户可读
    },

#     # ── 付费书 ──────────────────────────────────────────────
#     "1984 — George Orwell": {
#         "slug": "1984",
#         "repo": "https://raw.githubusercontent.com/lucuynswift/prism-data-1984/main",
#         "description": "A dystopian novel about totalitarianism.",
#         "free": False,
#     },
#
#     "Pride and Prejudice — Jane Austen": {
#         "slug": "pride_prejudice",
#         "repo": "https://raw.githubusercontent.com/lucuynswift/prism-data-pride-prejudice/main",
#         "description": "A classic romance novel.",
#         "free": False,
#     },
#
#     # ★ 新增书籍：复制上面一段，修改四个字段即可
#     # "书名 — 作者名": {
#     #     "slug": "唯一标识符",
#     #     "repo": "https://raw.githubusercontent.com/你的用户名/仓库名/main",
#     #     "description": "简介",
#     #     "free": False,
#     # },
# }