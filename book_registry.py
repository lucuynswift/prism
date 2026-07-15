# 文件位置：/opt/prism/app/book_registry.py

# ══════════════════════════════════════════
# ★ 每次新增/调整书籍只需修改这一个文件
# ★ 已全面对接服务器本地 33 本书的绝对路径
# ══════════════════════════════════════════

BOOK_REGISTRY = {
# ── 免费体验书籍（用于吸引新用户） ──────────────────────────────────────────────
    "Ulysses — James Joyce": {
        "slug": "Ulysses",
        "repo": "/opt/prism/app/books/Ulysses",
        "description": "Leopold Bloom's ordinary day in Dublin, reimagining Homer's Odyssey through stream of consciousness.",
        "free": True,
    },

# ── 付费专区书籍 (共 32 本) ──────────────────────────────────────────────────
    "A Farewell to Arms — Ernest Hemingway": {
        "slug": "A Farewell to Arms",
        "repo": "/opt/prism/app/books/A farewell to arms",
        "description": "A tragic love story set against the backdrop of World War I.",
        "free": True,
    },
    "A High Wind in Jamaica — Richard Hughes": {
        "slug": "A High Wind in Jamaica",
        "repo": "/opt/prism/app/books/A high wind in Jamaica",
        "description": "A psychological novel exploring the lives of children captured by pirates.",
        "free": True,
    },
    "A Passage to India — E.M. Forster": {
        "slug": "A Passage to India",
        "repo": "/opt/prism/app/books/A passage to India",
        "description": "An exploration of racism and colonialism in British India.",
        "free": True,
    },
    "A Portrait of the Artist as a Young Man — James Joyce": {
        "slug": "A Portrait of the Artist as a Young Man",
        "repo": "/opt/prism/app/books/A Portrait of the Artist as a Young Man",
        "description": "James Joyce's semi-autobiographical novel of intellectual and religious awakening.",
        "free": True,
    },
    "A Room with a View — E.M. Forster": {
        "slug": "A Room with a View",
        "repo": "/opt/prism/app/books/A Room with a View",
        "description": "A romance satirizing the stifling conventions of Edwardian society.",
        "free": True,
    },
    "Death Comes for the Archbishop — Willa Cather": {
        "slug": "Death Comes for the Archbishop",
        "repo": "/opt/prism/app/books/Death comes for the archbishop",
        "description": "A beautiful chronicle of a Catholic bishop's life in New Mexico.",
        "free": True,
    },
    "The Grapes of Wrath — John Steinbeck": {
        "slug": "The Grapes of Wrath",
        "repo": "/opt/prism/app/books/Grapes of wrath",
        "description": "An epic portrait of the Great Depression and Dust Bowl migration.",
        "free": True,
    },
    "Heart of Darkness — Joseph Conrad": {
        "slug": "Heart of Darkness",
        "repo": "/opt/prism/app/books/Heart of Darkness",
        "description": "A journey down the Congo River uncovering the depths of human cruelty.",
        "free": True,
    },
    "Howards End — E.M. Forster": {
        "slug": "Howards End",
        "repo": "/opt/prism/app/books/Howards End",
        "description": "A social critique of class and property in early 20th-century England.",
        "free": True,
    },
    "Kim — Rudyard Kipling": {
        "slug": "kim",
        "repo": "/opt/prism/app/books/Kim",
        "description": "A vibrant adventure story of imperialism and spirituality in India.",
        "free": True,
    },
    "Lord Jim — Joseph Conrad": {
        "slug": "Lord Jim",
        "repo": "/opt/prism/app/books/Lord Jim",
        "description": "A story of guilt, honor, and redemption on the high seas.",
        "free": True,
    },
    "Main Street — Sinclair Lewis": {
        "slug": "Main Street",
        "repo": "/opt/prism/app/books/Main Street",
        "description": "A sharp satire of small-town American conformity.",
        "free": True,
    },
    "Nostromo — Joseph Conrad": {
        "slug": "Nostromo",
        "repo": "/opt/prism/app/books/Nostromo",
        "description": "An intricate tale of political revolution and silver mining in South America.",
        "free": True,
    },
    "Of Human Bondage — W. Somerset Maugham": {
        "slug": "Of Human Bondage",
        "repo": "/opt/prism/app/books/Of Human Bondage",
        "description": "A deeply moving study of a young man's passions and struggles.",
        "free": True,
    },
    "Sons and Lovers — D.H. Lawrence": {
        "slug": "Sons and Lovers",
        "repo": "/opt/prism/app/books/Sons and Lovers",
        "description": "An intense exploration of family dynamics and industrial provincial life.",
        "free": True,
    },
    "The Age of Innocence — Edith Wharton": {
        "slug": "The Age of Innocence",
        "repo": "/opt/prism/app/books/The Age of Innocence",
        "description": "A brilliant critique of upper-class New York society in the 1870s.",
        "free": True,
    },
    "The Bridge of San Luis Rey — Thornton Wilder": {
        "slug": "The Bridge of San Luis Rey",
        "repo": "/opt/prism/app/books/The bridge of San Luis Rey",
        "description": "The philosophical investigation of why five people died in a bridge collapse.",
        "free": True,
    },
    "The Call of the Wild — Jack London": {
        "slug": "The Call of the Wild",
        "repo": "/opt/prism/app/books/The call of the wild",
        "description": "The classic adventure of Buck, a domesticated dog turned sled dog.",
        "free": True,
    },
    "The Golden Bowl — Henry James": {
        "slug": "The Golden Bowl",
        "repo": "/opt/prism/app/books/The Golden Bowl",
        "description": "An intense, complex drama of marriage and adultery.",
        "free": True,
    },
    "The Good Soldier — Ford Madox Ford": {
        "slug": "The Good Soldier",
        "repo": "/opt/prism/app/books/The Good Soldier",
        "description": "A masterpiece of unreliable narration exploring flawed relationships.",
        "free": True,
    },
    "The Great Gatsby — F. Scott Fitzgerald": {
        "slug": "The Great Gatsby",
        "repo": "/opt/prism/app/books/The Great Gatsby",
        "description": "A story of wealth, love, and the American Dream.",
        "free": True,
    },
    "The House of Mirth — Edith Wharton": {
        "slug": "The House of Mirth",
        "repo": "/opt/prism/app/books/The House of Mirth",
        "description": "The tragic social descent of Lily Bart in high-society New York.",
        "free": True,
    },
    "The Invisible Man — H.G. Wells": {
        "slug": "The Invisible Man",
        "repo": "/opt/prism/app/books/The Invisible Man_A Grotesque Romance",
        "description": "A classic sci-fi tale of an experiment in invisibility gone wrong.",
        "free": True,
    },
    "The Maltese Falcon — Dashiell Hammett": {
        "slug": "The Maltese Falcon",
        "repo": "/opt/prism/app/books/The Maltese falcon",
        "description": "The definitive hardboiled detective novel featuring Sam Spade.",
        "free": True,
    },
    "The Old Wives' Tale — Arnold Bennett": {
        "slug": "The Old Wives' Tale",
        "repo": "/opt/prism/app/books/The Old Wives' Tale",
        "description": "A life-spanning drama tracing the lives of two starkly different sisters.",
        "free": True,
    },
    "The Rainbow — D.H. Lawrence": {
        "slug": "The Rainbow",
        "repo": "/opt/prism/app/books/The Rainbow",
        "description": "The generational struggle of the Brangwen family in changing England.",
        "free": True,
    },
    "The Sound and the Fury — William Faulkner": {
        "slug": "The Sound and the Fury",
        "repo": "/opt/prism/app/books/The sound and the fury",
        "description": "A modernist masterpiece exploring the decline of a Southern family.",
        "free": True,
    },
    "The Sun Also Rises — Ernest Hemingway": {
        "slug": "The Sun Also Rises",
        "repo": "/opt/prism/app/books/The Sun Also Rises",
        "description": "Hemingway's definitive novel of the post-WWI Lost Generation.",
        "free": True,
    },
    "The Wings of the Dove (Vol. 1) — Henry James": {
        "slug": "The Wings of the Dove (Vol. 1)",
        "repo": "/opt/prism/app/books/The Wings of the Dove_Volume 1 of 2",
        "description": "A complex psychological tale of love, money, and manipulation (Volume 1).",
        "free": True,
    },
    "The Wings of the Dove (Vol. 2) — Henry James": {
        "slug": "The Wings of the Dove (Vol. 2)",
        "repo": "/opt/prism/app/books/The Wings of the Dove_Volume II",
        "description": "A complex psychological tale of love, money, and manipulation (Volume 2).",
        "free": True,
    },
    "Winesburg, Ohio — Sherwood Anderson": {
        "slug": "Winesburg, Ohio",
        "repo": "/opt/prism/app/books/Winesburg, Ohio",
        "description": "A collection of interrelated short stories depicting small-town loneliness.",
        "free": True,
    },
    "Zuleika Dobson — Max Beerbohm": {
        "slug": "Zuleika Dobson",
        "repo": "/opt/prism/app/books/Zuleika Dobson",
        "description": "A classic satirical novel about a dangerous femme fatale at Oxford.",
        "free": True,
    },
    "Alice’s Adventures in Wonderland": {
        "slug": "Alice’s Adventures in Wonderland",
        "repo": "/opt/prism/app/books/Alice’s Adventures in Wonderland",
        "description": "A classic fantasy novel about a young girl who tumbles down a rabbit hole into a whimsical, nonsensical world filled with peculiar creatures.",
        "free": True,
    },
}