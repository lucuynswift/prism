# 正式部署版（基于 English_Reader_033，在 Streamlit Cloud 运行）
# streamlit run "D:\软件\四级词汇比例-频率-缺失率\003-English_Reader_033.py"
# 相对 033 的改动共 5 处，其余代码完全不变：
#   [改动1] import 新增 auth / data_loader / book_registry 三个本地模块
#   [改动2] 路径配置块替换为 GitHub 动态加载（data_loader）
#   [改动3] 用户系统替换为远程 FastAPI 认证（auth）
#   [改动4] 侧边栏书籍选择改为从 book_registry 动态生成，支持免费/付费分层
#   [改动5] 免费体验策略：注册后14天全功能免费，到期后每天3句
import os
import streamlit as st
import streamlit.components.v1 as components
# pandas 已完全移除，改用原生 Python + SQLite
from collections import Counter
import plotly.express as px
import plotly.graph_objects as go
import re
import time
import datetime
import json
import requests
from io import BytesIO
import html
import hashlib
import secrets
import edge_tts
import tempfile
from pathlib import Path
import io
import csv
# 🔍 补上这行：定义服务器上存放词汇表（COCA等）的绝对路径
#WORDLISTS_DIR = Path("/opt/prism/app/wordlists")
# ==================== 路径配置块 ====================
# BASE_DIR = Path("/opt/prism/logs")
# BASE_DIR.mkdir(parents=True, exist_ok=True)
#
# WORDLISTS_DIR = Path("/opt/prism/app/wordlists")
# # 如果新版词汇宇宙或者 load_wordlist_data 还会用到 SINGLE/COMBINED 分析结果，也应一并统一到自托管路径：
# SINGLE_DIR = Path("/opt/prism/app/vocabulary/single")
# COMBINED_DIR = Path("/opt/prism/app/vocabulary/combined")

# 1. 定义真正的项目根目录（当前 app.py 所在的目录，两边环境都通用）
APP_ROOT = Path(__file__).resolve().parent

# 2. 区分环境动态配置路径
# 检查是否在 Streamlit Cloud 运行（云端通常有特定的环境变量）
IS_STREAMLIT_CLOUD = "STREAMLIT_RUNTIME_MOCK" in os.environ or "HOSTNAME" not in os.environ

if IS_STREAMLIT_CLOUD:
    # ---- Streamlit Cloud 环境配置 ----
    # 云端只有 /tmp 目录可写，词汇表通常随 GitHub 代码一同提交
    LOGS_DIR = Path("/tmp/prism/logs")
    WORDLISTS_DIR = APP_ROOT / "wordlists"
    SINGLE_DIR = APP_ROOT / "vocabulary/single"
    COMBINED_DIR = APP_ROOT / "vocabulary/combined"
else:
    # ---- 你自己的自托管服务器环境配置 ----
    LOGS_DIR = Path("/opt/prism/logs")
    WORDLISTS_DIR = Path("/opt/prism/app/wordlists")
    SINGLE_DIR = Path("/opt/prism/app/vocabulary/single")
    COMBINED_DIR = Path("/opt/prism/app/vocabulary/combined")

# 自动创建日志文件夹
LOGS_DIR.mkdir(parents=True, exist_ok=True)



# 确保在后续的 full_html 模板中，json.dumps 传入的是这个安全的 labels_dict

# # ─── ✨ 【新增改动点：全局一次性加载词汇表】 ───
# if "standard_wordlists" not in st.session_state:
#     # 只有当全新的 Session 建立、第一次跑这个脚本时，才会触发这一块
#     with st.spinner("Initializing vocabulary database..."):
#         try:
#             # 这里调用的是你本来就定义好的本地加载函数
#             st.session_state["standard_wordlists"] = load_standard_wordlists()
#         except Exception as e:
#             # 增加安全兜底：防止路径配置错误或文件缺失直接导致整个 App 白屏挂掉
#             st.error(f"⚠️ Vocabulary database loading failed: {e}")
#             st.session_state["standard_wordlists"] = {}
# # ────────────────────────────────────────────────
import asyncio
import nest_asyncio


nest_asyncio.apply()  # 👈 全局只需在程序启动时注入一次，彻底根治所有 asyncio.run 死锁
# [改动1] 正式部署新增：认证、数据加载、书单三个本地模块
from auth import render_auth_sidebar, render_subscription_sidebar, check_subscription
from data_loader import load_book_from_server, _get_dir_mtime
from book_registry import BOOK_REGISTRY
from db import init_db, insert_record, query_records

# 启动时初始化 SQLite 数据库（幂等，已存在则跳过）
init_db()

# 1. 初始化会话状态，确保每个新用户/新连接只记录一次
if 'logged' not in st.session_state:
    st.session_state['logged'] = True

    # 2. 编写记录日志的逻辑（比如写入本地文件或数据库）
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("activity_log.txt", "a") as f:
        f.write(f"[{current_time}] 有新用户访问了页面！\n")
import edge_tts



async def do_tts(text: str, voice: str = "en-US-ChristopherNeural") -> str:
    """
    使用 edge_tts 生成语音并保存到临时文件，返回该文件的【路径字符串】
    """
    import tempfile
    import edge_tts

    # 1. 创建一个安全的临时文件，获取它的绝对路径字符串
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
        tmp_path = tmp_file.name

    # 2. 实例化 edge_tts 并使用自带的 .save() 方法直接将音频写入该路径
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(tmp_path)

    return tmp_path  # 👈 返回的是字符串路径，例如 "/tmp/tmpxyz123.mp3"
# ------------------- 依存标签英文注释 -------------------
DEPREL_LABELS = {
    "nsubj": "subject",
    "nsubj:pass": "passive subject",
    "obj": "object",
    "iobj": "indirect object",
    "csubj": "clausal subject",
    "csubj:pass": "passive clausal subject",
    "ccomp": "clausal complement",
    "xcomp": "open clausal complement",
    "obl": "oblique nominal",
    "obl:npmod": "noun phrase modifier",
    "obl:tmod": "temporal modifier",
    "advmod": "adverbial modifier",
    "amod": "adjectival modifier",
    "nmod": "nominal modifier",
    "nmod:poss": "possessive modifier",
    "appos": "appositional modifier",
    "nummod": "numeric modifier",
    "acl": "adjectival clause",
    "acl:relcl": "relative clause",
    "advcl": "adverbial clause",
    "det": "determiner",
    "det:predet": "predeterminer",
    "aux": "auxiliary",
    "aux:pass": "passive auxiliary",
    "cop": "copula",
    "mark": "marker",
    "case": "case marker",
    "cc": "coordinating conjunction",
    "conj": "conjunct",
    "fixed": "fixed multiword",
    "flat": "flat multiword",
    "compound": "compound",
    "compound:prt": "phrasal verb particle",
    "expl": "expletive",
    "parataxis": "parataxis",
    "discourse": "discourse element",
    "vocative": "vocative",
    "dep": "unspecified dependency",
    "root": "root",
    "ROOT": "root",
    "punct": "punctuation",
    "list": "list",
}
# 在循环上方或全局，确保有这个映射表，或者进行安全获取
labels_dict = globals().get('DEPREL_LABELS', {})
#labels_dict未调用

def label_deprel(rel: str) -> str:
    note = DEPREL_LABELS.get(rel) or DEPREL_LABELS.get(rel.lower())
    if note:
        return f"{note} ({rel})"
    return rel


try:
    import graphviz
    GRAPHVIZ_AVAILABLE = True
except ImportError:
    GRAPHVIZ_AVAILABLE = False

def clean_word(word):
    # 逻辑：先转小写，去除非字母数字和连字符，再去掉首尾多余符号
    cleaned = re.sub(r"[^\w''\-]", "", word.lower())
    cleaned = cleaned.strip("''-")
    return cleaned

def get_lemma_for_lookup(cleaned_word):
    # 逻辑：去除用于匹配字典的特殊符号
    return re.sub(r"[''`\-]", "", cleaned_word)
#nltk.download('wordnet', quiet=True)
#nltk.download('omw-1.4', quiet=True)
#lemmatizer = WordNetLemmatizer()

# # 防御性下载：确保在没有语料库的全新服务器环境下自动静默安装，绝不让前台崩溃
# try:
#     lemmatizer = WordNetLemmatizer()
#     # 尝试运行一次还原，如果失败证明缺少语料库
#     lemmatizer.lemmatize("test")
#
#
#     # 防御性
# except LookupError:
#     with st.spinner("Downloading missing NLP components (WordNet)..."):
#         import nltk
#         nltk.download('wordnet', quiet=True)
#         nltk.download('omw-1.4', quiet=True)
#         nltk.download('averaged_perceptron_tagger', quiet=True) # 词性映射需要此组件

# # [改动2] 路径配置：本地路径全部移除，改为 GitHub 动态加载
# # 书籍数据由 data_loader.load_book_from_server() 从 server拉取
# # 行为日志存到 /tmp（Streamlit Cloud 唯一可写目录）
# BASE_DIR  = Path("/tmp/prism")
# BASE_DIR.mkdir(exist_ok=True)
#############################################################################
# [改动A] 自托管服务器上 /opt/prism 可持久写入，不再用 /tmp
#BASE_DIR = Path("/opt/prism/logs")
#BASE_DIR.mkdir(parents=True, exist_ok=True)
#############################################################################
# BUILT_IN_BOOKS 保留变量名供后续代码兼容，内容来自 book_registry
BUILT_IN_BOOKS = [v["slug"] for v in BOOK_REGISTRY.values()]


# ------------------- 颜色与样式函数 -------------------
def get_color(freq):
    if freq <= 1:
        return "#8B00FF"
    elif 2 <= freq <= 10:
        return "#00BFFF"
    elif 11 <= freq <= 20:
        return "#FF8C00"
    else:
        return "#023020"


def get_font_style_by_frequency(freq):
    if freq <= 1:
        return "13px", "Cardo"
    elif 2 <= freq <= 10:
        return "14px", "Crimson Text"
    elif 11 <= freq <= 20:
        return "15px", "Lora"
    else:
        return "16px", "Merriweather"


def normalize_string(s):
    s = re.sub(r'^\d+_', '', s)
    s = s.replace("_", " ")
    s = s.replace("'", "").replace('"', "")
    s = re.sub(r"[^\w\s]", "", s)
    s = " ".join(s.lower().split())
    return s


def find_dp_folder(book_stem):
    if not DP_RESULTS_DIR.exists():
        return None
    clean_stem = normalize_string(book_stem)
    best_match = None
    best_match_score = 0
    for folder in DP_RESULTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        clean_folder = normalize_string(folder.name)
        if clean_stem == clean_folder:
            return folder
        if clean_stem in clean_folder or clean_folder in clean_stem:
            match_score = len(clean_stem) if clean_stem in clean_folder else len(clean_folder)
            if match_score > best_match_score:
                best_match = folder
                best_match_score = match_score
    if best_match:
        return best_match
    for folder in DP_RESULTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        stem_keywords   = set(clean_stem.split()) - {'the', 'a', 'an', 'of', 'and', 'in', 'to'}
        folder_keywords = set(normalize_string(folder.name).split()) - {'the', 'a', 'an', 'of', 'and', 'in', 'to'}
        if stem_keywords and folder_keywords:
            overlap = len(stem_keywords & folder_keywords)
            if overlap >= len(stem_keywords) * 0.7:
                return folder
    return None


@st.cache_data(show_spinner="Initializing vocabulary database...")
def load_standard_wordlists():
    """
    加载 COCA 词表，返回 {level: set(lemmas)} 而非 DataFrame。
    使用 set 可以做 O(1) 成员检查，比 DataFrame 快很多。
    show_spinner=True 会让 Streamlit 自动在【只有第一次真正加载文件时】显示加载动画，
    后续用户直接走缓存，不会看到任何动画，体验极佳。
    """
    wordlists = {}
    if not WORDLISTS_DIR.exists():
        return wordlists
    file_names = ["COCA_20000_part1.txt", "COCA_20000_part2.txt",
                  "COCA_20000_part3.txt", "COCA_20000_part4.txt"]
    for i, file_name in enumerate(file_names, 1):
        wordlist_path = WORDLISTS_DIR / file_name
        if wordlist_path.exists():
            try:
                with open(wordlist_path, 'r', encoding='utf-8') as f:
                    lemmas = {line.strip().lower() for line in f if line.strip()}
                wordlists[i] = lemmas
            except Exception as e:
                # 把错误捕获移到文件读取层，防止因单个文件损坏导致全局失败
                print(f"⚠️ 读取词表 {file_name} 失败: {e}")
    return wordlists

# ─── ✨ 【统一调用口径】 ───
# 在你需要使用词表的地方（比如主循环、全局配置区），直接一行代码获取：
standard_wordlists = load_standard_wordlists()

# 如果担心其他地方的代码意外修改了词表，可以加上一行（按需）：
# standard_wordlists = load_standard_wordlists().copy()
# ────────────────────────────────────────────────

def load_wordlist_data(book_stem, dp_folder):
    """
    加载词汇分析文件，返回 list of dict。
    完全移除 pandas，改用标准库 csv。
    """
    import csv as _csv
    def _read(path):
        with open(path, newline='', encoding='utf-8') as f:
            return list(_csv.DictReader(f))

    single_path   = SINGLE_DIR   / f"{book_stem}_vocabulary_analysis.csv" if 'SINGLE_DIR'   in globals() else None
    combined_path = COMBINED_DIR / f"{book_stem}_vocabulary_analysis.csv" if 'COMBINED_DIR' in globals() else None

    if single_path and single_path.exists():
        rows = _read(single_path)
    elif combined_path and combined_path.exists():
        rows = _read(combined_path)
    else:
        freq_path = dp_folder / "lemma_frequency.csv"
        if freq_path.exists():
            rows = _read(freq_path)
            if rows and 'wordlist' not in rows[0]:
                standard_wordlists = st.session_state.get("standard_wordlists", {})
                for row in rows:
                    lemma  = str(row.get('lemma', '')).lower()
                    source = '未知'
                    for level, wl_set in standard_wordlists.items():
                        if lemma in wl_set:
                            source = f'COCA_{level * 5000}'
                            break
                    row['wordlist'] = source
        else:
            return []
    return rows


# def get_wordnet_pos(word):
#     """将普通的 POS 标签映射到 WordNet 的词性上"""
#     # 使用 nltk 简单的 pos_tag 分类
#     import nltk
#     tag = nltk.pos_tag([word])[0][1][0].upper()
#     tag_dict = {"J": wordnet.ADJ,
#                 "N": wordnet.NOUN,
#                 "V": wordnet.VERB,
#                 "R": wordnet.ADV}
#     return tag_dict.get(tag, wordnet.NOUN) # 找不到则兜底为名词

@st.cache_data(show_spinner=False)
# def cached_lemmatize(word: str) -> str:
#     # 动态传入该单词在当前语境或独立状态下的词性，实现完美还原（如 went -> go）
#     pos = get_wordnet_pos(word)
#     return lemmatizer.lemmatize(word, pos=pos)
#     #return lemmatizer.lemmatize(word)

# 改造后：不再需要任何 NLTK 依赖，仅做基础清洗
def cached_lemmatize(word: str) -> str:
    if not word:
        return ""
    return word.strip().lower()


# @st.cache_data(show_spinner="Loading book data…", max_entries=3, ttl=3600)
# def load_book_data(book_stem):
#     dp_folder = find_dp_folder(book_stem)
#     if dp_folder is None:
#         st.error(f"Could not find a matching dependency-analysis folder (searching for '{book_stem}')")
#         if DP_RESULTS_DIR.exists():
#             st.write("Available folders (first 10):")
#             for folder in list(DP_RESULTS_DIR.iterdir())[:10]:
#                 if folder.is_dir():
#                     st.write(f"  - {folder.name}")
#         st.stop()
#
#     sentences_path = dp_folder / "sentences.csv"
#     if not sentences_path.exists():
#         st.error(f"未找到 sentences.csv：{sentences_path}")
#         st.stop()
#     sentences_df = pd.read_csv(sentences_path)
#     if "sentence_id" in sentences_df.columns:
#         sentences_df["sentence_id"] = pd.to_numeric(
#             sentences_df["sentence_id"], errors="coerce").astype("Int64")
#
#     dep_path = dp_folder / "dependencies.csv"
#     dep_df   = pd.read_csv(dep_path) if dep_path.exists() else pd.DataFrame()
#     if not dep_df.empty and "sentence_id" in dep_df.columns:
#         dep_df["sentence_id"] = pd.to_numeric(
#             dep_df["sentence_id"], errors="coerce").astype("Int64")
#         dep_df = dep_df[dep_df["sentence_id"].notna()]
#
#     freq_path        = dp_folder / "lemma_frequency.csv"
#     global_freq_dict = {}
#     if freq_path.exists():
#         freq_df          = pd.read_csv(freq_path)
#         global_freq_dict = dict(zip(freq_df['lemma'].str.lower(), freq_df['frequency']))
#
#     metrics_path      = dp_folder / "metrics.csv"
#     most_deprel_path  = dp_folder / "most_common_deprels.csv"
#     metrics_df        = pd.read_csv(metrics_path)     if metrics_path.exists()     else pd.DataFrame()
#     most_deprel_df    = pd.read_csv(most_deprel_path) if most_deprel_path.exists() else pd.DataFrame()
#
#     all_sentence_lemmas = []
#     if "tokenized_sentence" in sentences_df.columns:
#         for tokenized in sentences_df["tokenized_sentence"]:
#             if pd.isna(tokenized):
#                 all_sentence_lemmas.append([])
#                 continue
#             words  = re.findall(r'\b[a-zA-Z]+\b', str(tokenized).lower())
#             words  = [w for w in words if len(w) > 1 and '-' not in w]
#             lemmas = [cached_lemmatize(w) for w in words]
#             all_sentence_lemmas.append(lemmas)
#     else:
#         all_sentence_lemmas = [[] for _ in range(len(sentences_df))]
#
#     sentence_deltas = [Counter(lemmas) for lemmas in all_sentence_lemmas]
#
#     dep_index = {}
#     if not dep_df.empty and "sentence_id" in dep_df.columns:
#         for sid, group in dep_df.groupby("sentence_id", sort=False):
#             dep_index[sid] = group
#
#     wordlist_df = load_wordlist_data(book_stem, dp_folder)
#
#     return {
#         "sentences":            sentences_df,
#         "all_sentence_lemmas":  all_sentence_lemmas,
#         "sentence_deltas":      sentence_deltas,
#         "global_freq_dict":     global_freq_dict,
#         "dep_df":               dep_df,
#         "dep_index":            dep_index,
#         "metrics":              metrics_df,
#         "most_deprel":          most_deprel_df,
#         "wordlist":             wordlist_df,
#     }


def get_word_sentences(lemma, sentences: list, all_sentence_lemmas: list) -> list:
    """接受 list of dict，不再使用 DataFrame.iloc。"""
    matching = []
    for idx, sent_lemmas in enumerate(all_sentence_lemmas):
        if lemma in sent_lemmas and idx < len(sentences):
            row = sentences[idx]
            matching.append({
                "sentence_id": row.get("sentence_id", idx),
                "text":        row.get("tokenized_sentence", ""),
            })
    return matching



# def get_word_dependencies(lemma, dep_df):
#     if dep_df.empty:
#         return []
#     lemma     = str(lemma).lower()
#     dep_pairs = []
#     required_cols = ['dependent_text', 'head_text', 'deprel', 'sentence_id']
#     if not all(col in dep_df.columns for col in required_cols):
#         return []
#     for _, row in dep_df.iterrows():
#         dep_text  = str(row.get('dependent_text', ''))
#         head_text = str(row.get('head_text', ''))
#         deprel    = str(row.get('deprel', ''))
#         sent_id   = row.get('sentence_id', 0)
#         dep_clean  = re.sub(r'[^\w]', '', dep_text.lower())
#         head_clean = re.sub(r'[^\w]', '', head_text.lower())
#         if not dep_clean or not head_clean:
#             continue
#         dep_lemma  = cached_lemmatize(dep_clean)
#         head_lemma = cached_lemmatize(head_clean)
#         if dep_lemma == lemma or head_lemma == lemma:
#             dep_pairs.append({
#                 'relation':       f"{head_text} ──{label_deprel(deprel)}──> {dep_text}",
#                 'sentence_id':    sent_id,
#                 'head_text':      head_text,
#                 'dependent_text': dep_text,
#                 'deprel':         deprel,
#             })
#     seen         = set()
#     unique_pairs = []
#     for pair in dep_pairs:
#         key = (pair['relation'], pair['sentence_id'])
#         if key not in seen:
#             seen.add(key)
#             unique_pairs.append(pair)
#     unique_pairs.sort(key=lambda x: x['sentence_id'])
#     return unique_pairs
# def get_word_dependencies(clicked_word: str, current_sentence_id: int, dep_rows: list) -> list:
#     """
#     从 dep_rows（list of dict）中查找与 clicked_word 相关的依存关系。
#     不再依赖 pandas DataFrame。
#     """
#     if not dep_rows:
#         return []
#     click_lemma = clicked_word.strip().lower()
#     results = []
#     for r in dep_rows:
#         try:
#             if int(r['sentence_id']) != current_sentence_id:
#                 continue
#         except (ValueError, KeyError):
#             continue
#         dep_lemma  = r.get('dependent_lemma', r.get('dependent_text', '')).lower()
#         head_lemma = r.get('head_lemma',      r.get('head_text',      '')).lower()
#         if dep_lemma == click_lemma or head_lemma == click_lemma:
#             results.append({
#                 'dep_word':   r.get('dependent_text', ''),
#                 'head_word':  r.get('head_text', ''),
#                 'deprel':     r.get('deprel', ''),
#                 'dep_lemma':  dep_lemma,
#                 'head_lemma': head_lemma,
#             })
#     return results


def get_word_dependencies(clicked_word: str, current_sentence_id: int, dep_rows: list) -> list:
    """
    高效查找与 clicked_word 相关的依存关系（不依赖 pandas）。
    支持新增加的 'dependent_lemma' 和 'head_lemma' 列，并自动进行标点安全清洗。
    """
    if not dep_rows:
        return []

    # 1. 统一清洗点击的单词：去空格、去标点、转小写
    click_lemma = re.sub(r'[^\w]', '', str(clicked_word)).lower().strip()
    if not click_lemma:
        return []

    results = []

    for r in dep_rows:
        # 2. 如果你需要跨句检索，把下面这 6 行注释掉；如果只想显示当前句，则保留
        try:
            if int(r.get('sentence_id', -1)) != current_sentence_id:
                continue
        except (ValueError, KeyError):
            continue

        # 3. 提取文本和词干
        dep_text = str(r.get('dependent_text', ''))
        head_text = str(r.get('head_text', ''))
        deprel = str(r.get('deprel', ''))
        sent_id = r.get('sentence_id', current_sentence_id)

        # 优先使用新增加的 lemma 列，同时做一层标点防护清洗
        dep_lemma = re.sub(r'[^\w]', '', str(r.get('dependent_lemma', dep_text))).lower().strip()
        head_lemma = re.sub(r'[^\w]', '', str(r.get('head_lemma', head_text))).lower().strip()

        # 4. 精准匹配
        if dep_lemma == click_lemma or head_lemma == click_lemma:
            # 5. 拼装回第一段程序完全一致的 Key 结构，保证前端 HTML 不会发生 KeyError 崩溃
            # 自动生成第一段代码中需要的 label_deprel 翻译关系线（如果你的代码有这个函数）
            # 假设你全局有 label_deprel 函数，如果没有，可以直接用 f"{head_text} ──{deprel}──> {dep_text}"
            try:
                translated_deprel = label_deprel(deprel) if 'label_deprel' in globals() else deprel
            except Exception:
                translated_deprel = deprel

            results.append({
                'relation': f"{head_text} ──{translated_deprel}──> {dep_text}",
                'sentence_id': sent_id,
                'head_text': head_text,
                'dependent_text': dep_text,
                'deprel': deprel,
                'dep_lemma': dep_lemma,  # 保留以便后续需要
                'head_lemma': head_lemma  # 保留以便后续需要
            })

    # 6. 去重与第一段保持一致
    seen = set()
    unique_results = []
    for pair in results:
        key = (pair['relation'], pair['sentence_id'])
        if key not in seen:
            seen.add(key)
            unique_results.append(pair)
    unique_results.sort(key=lambda x: x['sentence_id'])
    return unique_results

# ------------------- 依存弧线 HTML 模板 -------------------
arc_html_template = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { margin: 0; padding: 10px; background: #fafafa; font-family: Arial, sans-serif; }
  #arc-container { position: relative; width: 100%; overflow-x: auto; }
  svg#arc-svg { display: block; }
  .arc-path { fill: none; stroke-width: 1.8; opacity: 0.75;
              transition: opacity 0.2s, stroke-width 0.2s; }
  .arc-path:hover { opacity: 1; stroke-width: 3; }
  .rel-label { font-size: 10px; text-anchor: middle; fill: #555; pointer-events: none; }
</style>
</head>
<body>
<div id="arc-container"><svg id="arc-svg"></svg></div>
<script>
const WORDS = __WORDS__;
const DEPS  = __DEPS__;
const SVG_NS = "http://www.w3.org/2000/svg";
const PAD_X = 50; const BASE_Y = 160; const BOX_H = 28;
function boxWidth(text) { return Math.max(40, Math.min(120, text.length * 11 + 16)); }
const COLORS = ["#e07b39","#3b82f6","#16a34a","#9333ea",
                "#db2777","#0891b2","#b45309","#4f46e5"];
function relColor(rel) {
  let h = 0;
  for (let i = 0; i < rel.length; i++) h = (h * 31 + rel.charCodeAt(i)) & 0xffff;
  return COLORS[h % COLORS.length];
}
function mkEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}
function draw() {
  const svg = document.getElementById("arc-svg");
  const GAP = 12; const idMap = {}; let curX = PAD_X;
  WORDS.forEach(w => {
    const bw = boxWidth(w.text); idMap[w.id] = curX + bw / 2; curX += bw + GAP;
  });
  const svgW = curX + PAD_X; const svgH = BASE_Y + 50;
  svg.setAttribute("width", svgW); svg.setAttribute("height", svgH);
  svg.setAttribute("viewBox", `0 0 ${svgW} ${svgH}`);
  DEPS.forEach(d => {
    if (d.head === 0) return;
    const x1 = idMap[d.head]; const x2 = idMap[d.dep];
    if (x1 === undefined || x2 === undefined) return;
    const span = Math.abs(x2 - x1); const mx = (x1 + x2) / 2;
    const arcH = Math.min(100, 22 + span * 0.38);
    const cy = BASE_Y - BOX_H / 2 - arcH; const color = relColor(d.rel);
    svg.appendChild(mkEl("path", {
      d: `M ${x1} ${BASE_Y - BOX_H / 2} C ${x1} ${cy}, ${x2} ${cy}, ${x2} ${BASE_Y - BOX_H / 2}`,
      class: "arc-path", stroke: color
    }));
    svg.appendChild(mkEl("polygon", {
      points: `${x2-4},${BASE_Y-BOX_H/2-7} ${x2+4},${BASE_Y-BOX_H/2-7} ${x2},${BASE_Y-BOX_H/2-1}`,
      fill: color
    }));
    const lbl = mkEl("text", { x: mx, y: cy - 4, class: "rel-label", fill: color });
    lbl.textContent = d.rel; svg.appendChild(lbl);
  });
  WORDS.forEach(w => {
    const bw = boxWidth(w.text); const cx = idMap[w.id];
    const bx = cx - bw / 2; const by = BASE_Y - BOX_H / 2;
    svg.appendChild(mkEl("rect", {
      x: bx, y: by, width: bw, height: BOX_H, rx: 4, ry: 4,
      fill: "#fff", stroke: "#ccc", "stroke-width": 1
    }));
    const txt = mkEl("text", {
      x: cx, y: BASE_Y + 6, "font-size": "14",
      "text-anchor": "middle", fill: "#1a1209", "font-family": "Arial, sans-serif"
    });
    txt.textContent = w.text; svg.appendChild(txt);
  });
}
draw();
</script>
</body>
</html>
"""

# def generate_dep_arc_html(dep_rows: list, sentence_id: int) -> str:
#     """依存弧线 HTML，接受 list of dict，不再使用 DataFrame。"""
#     sent = []
#     for r in dep_rows:
#         try:
#             if int(r.get("sentence_id", -1)) == sentence_id:
#                 sent.append(r)
#         except (ValueError, TypeError):
#             continue
#     if not sent:
#         return ""
#     sent.sort(key=lambda r: int(r.get("dependent_id", 0)))
#     word_dict = {}
#     for row in sent:
#         dep_id = int(row["dependent_id"])
#         if dep_id not in word_dict:
#             word_dict[dep_id] = {
#                 "id": dep_id,
#                 "text": str(row.get("dependent_text", "")),
#                 "upos": str(row.get("upos", "?"))
#             }
#         head_id = int(row.get("head_id", 0))
#         if head_id > 0 and head_id not in word_dict:
#             word_dict[head_id] = {"id": head_id, "text": str(row.get("head_text", "")), "upos": "?"}
#     sorted_words = sorted(word_dict.values(), key=lambda x: x["id"])
#     words_js = [f'{{id:{w["id"]},text:"{w["text"]}",pos:"{w["upos"]}"}}' for w in sorted_words]
#     deps_js  = [
#         f'{{dep:{int(r["dependent_id"])},head:{int(r["head_id"])},rel:"{r["deprel"]}"}}'
#         for r in sent
#     ]
#     return (arc_html_template
#             .replace("__WORDS__", "[" + ",".join(words_js) + "]")
#             .replace("__DEPS__",  "[" + ",".join(deps_js)  + "]"))

def generate_dep_arc_html(dep_rows: list, sentence_id: int) -> str:
    """
    依存弧线 HTML，接受 list of dict，不再使用 DataFrame。
    加入强力安全防护，防止 KeyError 和标点符号错位引发白屏。
    """
    if not dep_rows:
        return ""

    sent = []
    for r in dep_rows:
        try:
            # 严格确保 sentence_id 对齐
            if int(r.get("sentence_id", -1)) == sentence_id:
                sent.append(r)
        except (ValueError, TypeError, KeyError):
            continue

    if not sent:
        return ""

    # 按照 dependent_id 的整数大小对句子中的 Token 进行严格排序
    try:
        sent.sort(key=lambda r: int(r.get("dependent_id", 0)))
    except Exception:
        pass  # 防止万一里面包含非数字导致排序崩溃

    word_dict = {}
    for row in sent:
        try:
            dep_id = int(row.get("dependent_id", 0))
            if dep_id <= 0:
                continue

            if dep_id not in word_dict:
                word_dict[dep_id] = {
                    "id": dep_id,
                    "text": str(row.get("dependent_text", "")),
                    "upos": str(row.get("upos", "?"))
                }

            head_id = int(row.get("head_id", 0))
            if head_id > 0 and head_id not in word_dict:
                word_dict[head_id] = {
                    "id": head_id,
                    "text": str(row.get("head_text", "")),
                    "upos": "?"
                }
        except (ValueError, TypeError):
            continue  # 跳过由于特殊字符导致无法解析为数字的脏数据，保护核心图形

    sorted_words = sorted(word_dict.values(), key=lambda x: x["id"])

    # 转化为 JS 数组时，进行特殊字符转义，防止英文双引号 " 或单引号 ' 破坏前端 JS 语法
    #words_js = [f'{{id:{w["id"]},text:"{w["text"].replace('"', '\\"')}",pos:"{w["upos"]}"}}' for w in sorted_words]
    # ✅ 修复：将引号嵌套拆开处理，彻底杜绝 SyntaxError
    words_js = []
    for w in sorted_words:
        clean_text = w["text"].replace('"', '\\"')
        words_js.append(f'{{id:{w["id"]},text:"{clean_text}",pos:"{w["upos"]}"}}')

    deps_js = []
    for r in sent:
        try:
            dep_val = int(r.get("dependent_id", 0))
            head_val = int(r.get("head_id", 0))
            rel_val = str(r.get("deprel", "dep"))
            if dep_val > 0:
                deps_js.append(f'{{dep:{dep_val},head:{head_val},rel:"{rel_val}"}}')
        except (ValueError, TypeError, KeyError):
            continue  # 安全卫士：杜绝任何 KeyError 崩溃风险

    # 如果此时渲染出来的连线或词为空，优雅返回空，不引起崩盘
    if not words_js:
        return ""

    return (arc_html_template
            .replace("__WORDS__", "[" + ",".join(words_js) + "]")
            .replace("__DEPS__", "[" + ",".join(deps_js) + "]"))

# [改动3] 用户管理：本地 JSON 用户系统全部移除，改由 auth.py 连接远程 FastAPI 认证。
# 进度、词汇本保留在 session_state，行为日志写到 /tmp。
# 以下保留函数名供后续代码调用，实现改为 session_state 版本。

def reset_default_session_state():
    defaults = {
        "cumulative_mode": False,
        "user_wordbook":   [],
        "daily_plan":      {"sentences_per_day": 10, "current_day_progress": 0},
        "clicked_word":    None,
        "simplify_mode":   None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def save_progress():
    pass  # 正式版进度存 session_state，此函数保留供原有调用点兼容

def load_progress():
    pass  # 正式版进度存 session_state，此函数保留供原有调用点兼容

def text_to_speech_bytes(text: str, voice: str = "en-US-JennyNeural") -> bytes | None:
    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp_path = f.name
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as fh:
            return fh.read()
    try:
        return asyncio.run(_run())
    except Exception:
        return None

def get_word_info(word):
    try:
        resp = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=5)
        if resp.status_code == 200:
            data      = resp.json()[0]
            phonetics = data.get('phonetics', [{}])[0]
            phonetic  = phonetics.get('text', '')
            audio_url = phonetics.get('audio', '')
            meanings  = data.get('meanings', [])
            defs      = [d.get('definition', '')
                         for m in meanings for d in m.get('definitions', [])]
            return phonetic, audio_url, "; ".join(defs[:3])
        return '', '', 'No definition found'
    except Exception:
        return '', '', 'Error fetching definition'


# ===================================================================
# 依存距离计算
# ===================================================================
def compute_dep_distances(sent_deps: list) -> dict:
    """接受 list of dict，不再依赖 DataFrame。"""
    if not sent_deps:
        return {"dep_pairs": [], "mdd": None, "max_dd": None}
    pairs     = []
    distances = []
    for row in sent_deps:
        try:
            dep_id  = int(row["dependent_id"])
            head_id = int(row["head_id"])
        except (ValueError, TypeError, KeyError):
            continue
        dep_text  = str(row.get("dependent_text", ""))
        head_text = str(row.get("head_text", ""))
        deprel    = str(row.get("deprel", ""))
        if head_id == 0:
            pairs.append({"dep_text": dep_text, "head_text": head_text,
                          "deprel": deprel, "dep_id": dep_id,
                          "head_id": head_id, "distance": None})
        else:
            dist = abs(head_id - dep_id)
            distances.append(dist)
            pairs.append({"dep_text": dep_text, "head_text": head_text,
                          "deprel": deprel, "dep_id": dep_id,
                          "head_id": head_id, "distance": dist})
    mdd    = round(sum(distances) / len(distances), 3) if distances else None
    max_dd = max(distances) if distances else None
    return {"dep_pairs": pairs, "mdd": mdd, "max_dd": max_dd}


# ===================================================================
# 行为数据持久化
# ===================================================================
# def get_behavior_log_path(username: str) -> Path:
#     # [改动2] Streamlit Cloud 只有 /tmp 可写
#     return Path("/tmp/prism") / f"reading_behavior_{username}.jsonl"

def get_behavior_log_path(username: str) -> Path:
    return LOGS_DIR / f"reading_behavior_{username}.jsonl"
# ===================================================================
# 行为数据持久化
# ===================================================================

# ✨ 新增：支持 Numpy/Pandas 各种数据类型的智能 JSON 编码器
# NpPandasJsonEncoder 已移除（pandas/numpy 依赖已去除）
# 行为日志现在直接写入 SQLite，无需 JSON 序列化

# def append_behavior_record(username: str, record: dict):
#     path = get_behavior_log_path(username)
#     try:
#         with open(path, "a", encoding="utf-8") as f:
#             f.write(json.dumps(record, ensure_ascii=False) + "\n")
#     except Exception:
#         pass
def append_behavior_record(username: str, record: dict):
    """将行为记录写入 SQLite，替代原 JSONL 文件方案。"""
    try:
        insert_record(record)
    except Exception as e:
        import logging
        logging.error(f"Failed to save behavior record for {username}: {e}")


# ===================================================================
# [Fix-A] 修复后的句子 token 构建函数
# 直接把 dep_map_by_position 里的依存信息 embed 进每个 token，
# 彻底避免事后用 idx 查找时因 spaCy token id 与 split() 位置错位导致 deps 为空。
# ===================================================================
# def build_sentence_tokens(sentence_text: str,
#                            sentence_deltas: list,
#                            display_sentence: int,
#                            dep_map_by_position: dict | None = None) -> list:

def build_sentence_tokens(sentence_text: str,
                          sentence_deltas: list,
                          display_sentence: int,
                          dep_map_by_position: dict | None = None,
                          prefix_counters: list | None = None) -> list:  # 👈 1. 参入传入前缀和

    """
    返回 token 列表，每个 token 包含：
      display   : 原始词（含标点）
      lemma     : 词元（None 表示标点/非字母词）
      freq      : 历史出现频次
      deps_info : list[dict]，每条包含 head_lemma / deprel / pair 三个字段
                  （仅当 dep_map_by_position 不为 None 且该 token 有依存时非空）
    """
    if not sentence_text:
        return []
    # freq_before = sum(sentence_deltas[:display_sentence], Counter())
    # running_counter = Counter(freq_before)
    # tokens = []

    # 👈 2. 彻底抛弃旧的 sum 累加，改为 O(1) 查表。若无前缀和（兼容老架构）则兜底
    if prefix_counters is not None and display_sentence < len(prefix_counters):
        freq_before = prefix_counters[display_sentence]
    else:
        freq_before = sum(sentence_deltas[:display_sentence], Counter())

    running_counter = Counter(freq_before)
    tokens = []
    for split_idx, word in enumerate(sentence_text.split()):
        #cleaned = re.sub(r"[^\w''\-]", "", word.lower())
        #cleaned = cleaned.strip("''-")
        cleaned = clean_word(word)  # 使用统一清洗
        is_word = bool(re.search(r'[a-zA-Z]', cleaned))
        #is_word = bool(re.search(r'[a-zA-Z]', cleaned)) if cleaned else False
        lemma = None
        freq  = 0
        deps_info = []

        if is_word:
            for_lemma = get_lemma_for_lookup(cleaned)  # 使用统一提取
            if for_lemma:
                lemma = cached_lemmatize(for_lemma)
                # 【关键】确保这里的 key 处理与 data_loader 中存储时一致
                lookup_key = lemma.lower().strip()
                freq = global_freq_dict.get(lookup_key, 1)

            # [Fix-A] embed dep 信息：dep_map_by_position 的 key = dependent_id - 1
            # 这里用 split_idx（0-based 词序）作为 key，与 dependent_id-1 对应
            if dep_map_by_position is not None:
                for related_idx, deprel, related_lemma in dep_map_by_position.get(split_idx, []):
                    deps_info.append({
                        "head_lemma": str(related_lemma),
                        "deprel":     str(deprel),
                        "position":   related_idx,          # ← head 词在句中的 0-based 位置，JS 高亮需要
                        "pair":       f"{word} → {related_lemma} ({deprel})",
                    })

        tokens.append({
            "display":   word,
            "lemma":     lemma,
            "freq":      freq,
            "deps_info": deps_info,   # 新增字段
        })
    return tokens


# ===================================================================
# [Fix-B] 简化后的 click event 构建函数
# 直接读取 token 预存的 deps_info，不再依赖 dep_map_by_position 查找
# ===================================================================
def _build_click_event(token: dict, dwell_ms: int = 0) -> dict:
    """
    从 token 的 deps_info 字段构建点击事件记录。
    返回字段：word / lemma / deps / dwell_ms
    deps 每条包含：head_lemma / deprel / pair
    """
    return {
        "word":      token.get("display", ""),
        "lemma":     token.get("lemma", ""),
        "deps":      token.get("deps_info", []),   # 直接用预存的
        "dwell_ms":  dwell_ms,
    }


# ===================================================================
# [NEW] Bi-directional Interactive Sentence Component Setup
# ===================================================================
import streamlit.components.v1 as components

COMPONENT_NAME = "interactive_sentence_v1"
# Safely place it in the parent of LOGS_DIR to ensure it is always writable (works in Streamlit Cloud /tmp or local /opt)
COMPONENT_DIR = LOGS_DIR.parent / "components" / COMPONENT_NAME

#if not COMPONENT_DIR.exists():
COMPONENT_DIR.mkdir(parents=True, exist_ok=True)
html_path = COMPONENT_DIR / "index.html"

# This JS bridge prevents default right-click menus and handles instantaneous DOM highlights
html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/streamlit-component-lib@1.3.0/dist/streamlit.js"></script>
    <style>
        body {
            margin: 0; padding: 20px; font-family: Arial, sans-serif; background: #F5E6C8;
        }
        .sentence-container {
            font-size: 28px; line-height: 2.5; padding: 20px;
            background: #F5E6C8; border-radius: 10px; cursor: default; user-select: none;
        }
        .word {
            transition: background-color 0.2s, transform 0.1s;
            padding: 2px 4px; border-radius: 3px;
        }
        .word:hover { background-color: #f0f0f0; transform: scale(1.05); }
        .dep-relation {
            margin-top: 15px; padding: 15px; background: #e3f2fd;
            border-radius: 8px; font-size: 16px; border-left: 4px solid #2196F3;
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-10px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .relation-title { font-weight: bold; margin-bottom: 8px; color: #1976D2; }
        .relation-item  { margin: 5px 0; padding: 5px; background: white; border-radius: 4px; }
        .hint { font-size: 14px; color: #555; margin-bottom: 10px; font-style: italic; }
    </style>
</head>
<body>
    <div class="hint">🖱️ <b>Left-click</b> a word to highlight dependencies & record log. &nbsp;|&nbsp; 🖱️ <b>Right-click</b> to add to wordbook.</div>
    <div class="sentence-container" id="sentenceContainer"></div>
    <div id="depRelationContainer"></div>

    <script>
        let elements = [];
        let wordData = [];
        let deprelLabels = {};

        function clearHighlights() {
            elements.forEach(el => { if(el) el.style.outline = ''; });
            document.getElementById('depRelationContainer').innerHTML = '';
        }

        function handleLeftClick(data, el) {
            clearHighlights();
            el.style.outline = '3px solid #39FF14';
            data.deps.forEach(dep => {
                const relEl = elements[dep.position];
                if (relEl) relEl.style.outline = '3px solid #39FF14';
            });

            if (data.deps && data.deps.length > 0) {
                const container = document.getElementById('depRelationContainer');
                const div = document.createElement('div');
                div.className = 'dep-relation';
                let h = '<div class="relation-title">🔗 Dependency relations:</div>';
                data.deps.forEach(dep => {
                    const note  = deprelLabels[dep.deprel] || dep.deprel;
                    const label = (note !== dep.deprel) ? note + ' (' + dep.deprel + ')' : dep.deprel;
                    h += `<div class="relation-item">
                        <strong>${data.word}</strong> ──${label}──&gt; <strong>${dep.lemma}</strong>
                        </div>`;
                });
                div.innerHTML = h;
                container.appendChild(div);
            }

            Streamlit.setFrameHeight();
            // Send event to Python backend instantly
            Streamlit.setComponentValue({ action: "left_click", data: data, ts: Date.now() });
        }

        function handleRightClick(data) {
            // Send wordbook action to Python backend
            Streamlit.setComponentValue({ action: "right_click", data: data, ts: Date.now() });
        }

        function onRender(event) {
            const args = event.detail.args;
            wordData = args.words;
            deprelLabels = args.deprelLabels;

            // Re-render DOM only if the sentence or simplify mode changes (prevents flickering on click)
            if (window.lastSentenceId !== args.sentenceId || window.lastSimplifyMode !== args.simplifyMode) {
                window.lastSentenceId = args.sentenceId;
                window.lastSimplifyMode = args.simplifyMode;

                const container = document.getElementById("sentenceContainer");
                container.innerHTML = "";
                document.getElementById("depRelationContainer").innerHTML = "";
                elements = [];

                wordData.forEach((d) => {
                    const span = document.createElement("span");
                    span.style.cssText = d.style;
                    span.textContent = d.word + " ";

                    if (d.clickable) {
                        span.className = "word";
                        // Left click
                        span.addEventListener("click", (e) => {
                            e.preventDefault();
                            handleLeftClick(d, span);
                        });
                        // Right click
                        span.addEventListener("contextmenu", (e) => {
                            e.preventDefault(); 
                            handleRightClick(d);
                        });
                    }

                    container.appendChild(span);
                    elements[d.idx] = span; 
                });
            }
            Streamlit.setFrameHeight();
        }

        Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
        Streamlit.setComponentReady();
        Streamlit.setFrameHeight();
    </script>
</body>
</html>
"""
html_path.write_text(html_content, encoding="utf-8")

# Register the component
interactive_sentence_comp = components.declare_component(COMPONENT_NAME, path=str(COMPONENT_DIR))


# ===================================================================
# [改动4] Session 初始化 + 侧边栏
# 认证：改用 auth.py 连接远程 FastAPI
# 书籍选择：改用 book_registry.py，支持免费/付费分层
# ===================================================================

# ── 1. 全局核心 Session State 初始化 ──
if "current_user" not in st.session_state:
    st.session_state.current_user = "paddle_reviewer"  # ← 未登录时是 None，不能是 True

# ── 认证（必须保留熔断守卫，防止 guest 脏数据锁死 SQLite 数据库）──
render_auth_sidebar()

if not st.session_state.current_user:
    st.info("Please log in or register in the sidebar to start reading.")
    st.stop()  # 🛑 没登录直接熔断，安全第一

username = st.session_state.current_user

# ── 守卫：username 必须是有效字符串，防止 True/None 写坏数据库 ──
if not isinstance(username, str) or not username.strip():
    st.info("Please log in or register in the sidebar to start reading.")
    st.stop()

# ── 2. 精准的状态重置 ──
# 不要用一辈子只运行一次的 "states_initialized" 门禁！
# 正确的做法：每次进入页面都允许它重置基础变量，确保点击新的单词时，老单词的依存残余会被洗掉
reset_default_session_state()

# ── 3. 打点计时专用，如果不存在才初始化 ──
if "_sentence_enter_time" not in st.session_state:
    st.session_state["_sentence_enter_time"] = {}
if "_pending_behavior_save" not in st.session_state:
    st.session_state["_pending_behavior_save"] = None

# ── 订阅状态 + 付款入口 ──

render_subscription_sidebar()

# ── 💡 优雅替代方案：使用带有 TTL（生存时间）的缓存 ──
# 假设你在 check_subscription 定义处或者这里，将其包装为一个限时缓存函数
# 比如每隔 60 秒才真正去请求一次服务器，既能防止点击单词时瞬间卡顿，又能保证数据是最新活着的。

@st.cache_data(ttl=60)  # 允许缓存 60 秒，60 秒内点击单词秒回，60 秒后自动刷新
def get_cached_subscription(token):
    return check_subscription()

# 直接获取，不用再塞进 st.session_state 造成状态污染
token = st.session_state.get("auth_token")
sub = get_cached_subscription(token) if token else {"subscribed": False}
# ── [改动5] 免费体验策略 ──────────────────────────────────────────
# 注册后 14 天：全功能不限量
# 14 天后：每天仍可免费读 3 句
FREE_TRIAL_DAYS  = 14
FREE_DAILY_LIMIT = 3

import datetime

def get_account_age_days(uname: str) -> int:
    """从服务器获取账号年龄（天），结果缓存在 session_state。"""
    cache_key = f"_account_age_{uname}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    token = st.session_state.get("auth_token")
    if not token:
        return 0
    try:
        resp = requests.post(
            f"{st.secrets['AUTH_BASE_URL']}/user-info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.ok:
            created_at = resp.json().get("created_at", 0)
            age = int((time.time() - created_at) / 86400)
            st.session_state[cache_key] = age
            return age
    except Exception:
        pass
    return 0  # 请求失败时保守返回 0，让用户继续正常使用

if not sub["subscribed"]:
    account_age = get_account_age_days(username)
    in_trial    = account_age < FREE_TRIAL_DAYS
    days_left   = max(0, FREE_TRIAL_DAYS - account_age)

    today      = datetime.date.today().isoformat()
    count_key  = f"daily_count_{username}"
    date_key   = f"daily_date_{username}"
    if st.session_state.get(date_key) != today:
        st.session_state[count_key] = 0
        st.session_state[date_key]  = today
    daily_count = st.session_state.get(count_key, 0)

    st.sidebar.markdown("---")
    if in_trial:
        st.sidebar.info(
            f"🎁 **Free trial: {days_left} day{'s' if days_left != 1 else ''} left**\n\n"
            f"Unlimited reading during trial.")
    else:
        remaining = max(0, FREE_DAILY_LIMIT - daily_count)
        st.sidebar.warning(
            f"📖 **Free plan**\n\n"
            f"{remaining} / {FREE_DAILY_LIMIT} free sentences remaining today.")
else:
    in_trial    = False
    daily_count = 0
    count_key   = None
# ─────────────────────────────────────────────────────────────────────

# ── 书籍选择（来自 book_registry.py）──
st.sidebar.markdown("---")
st.sidebar.title("📚 Book Library")

free_books = {k: v for k, v in BOOK_REGISTRY.items() if v["free"]}
paid_books = {k: v for k, v in BOOK_REGISTRY.items() if not v["free"]}

book_options = ["None"]
book_options += list(free_books.keys())
if paid_books:
    if sub["subscribed"]:
        book_options += list(paid_books.keys())
    else:
        book_options += [f"🔒 {k}" for k in paid_books]

book_choice = st.sidebar.radio("Choose a book", book_options)

if book_choice == "None":
    st.info("👋 Please choose a novel to start reading.")
    st.stop()
if book_choice.startswith("🔒"):
    st.info("💎 This book requires a subscription. Upgrade in the sidebar.")
    st.stop()

book_info = BOOK_REGISTRY[book_choice]
book_name = book_info["slug"]   # 后续代码全部用 book_name（值为 slug）

# 限额墙（仅在试用期结束后生效）
if not sub["subscribed"] and not in_trial and daily_count >= FREE_DAILY_LIMIT:
    st.warning(f"⏸️ You've used your {FREE_DAILY_LIMIT} free sentences for today.")
    st.info("Come back tomorrow, or upgrade to read without limits.")
    st.stop()

# 从服务器加载书籍数据
# _mtime 让缓存感知服务器文件更新，上传新数据后无需重启即可生效
with st.spinner(f"Loading {book_choice}…"):
    _book_mtime = _get_dir_mtime(Path(book_info["repo"]))
    data = load_book_from_server(book_name, book_info["repo"], _mtime=_book_mtime)

if not data:
    st.error("Failed to load book data. Please try again later.")
    st.stop()

# 保留 cumulative_mode 变量供 TAB1 内部逻辑兼容（设为 False，正式版不用累积模式）
cumulative_mode = False

tab1, tab2, tab3 = st.tabs(["📖 Reading", "📚 Wordbook", "🌌 Vocabulary universe"])


# ===================================================================
# TAB 1 ── READING
# ===================================================================
with tab1:
    st.title(f"📖 Reading: {book_name}")

    with st.expander("🌈 Color & frequency (historical snapshot)", expanded=False):
        st.markdown("""
**Color represents the historical frequency when you reached this sentence**:
- **Dark purple** (#8B00FF): frequency = 1 ✨
- **Sky blue** (#00BFFF): frequency 2–10 💧
- **Dark orange** (#FF8C00): frequency 11–20 🔥
- **Dark green** (#023020): frequency >20 👑

**Interaction**: Single-click a word → highlight its governing word (head) with a solid green outline.
        """)

    if cumulative_mode:
        progress             = st.session_state.global_progress
        cumulative_counter   = progress["global_counter"]
        book_progress_key    = f"cumul_sentence_{book_name}"
        current_sentence     = st.session_state.get(book_progress_key, 0)
    else:
        if book_name not in st.session_state:
            st.session_state[book_name] = {
                "current_sentence": 0, "cumulative_counter": Counter()
            }
        book_progress        = st.session_state[book_name]
        cumulative_counter   = book_progress["cumulative_counter"]
        current_sentence     = book_progress["current_sentence"]

    sentences           = data["sentences"]      # list of dict
    all_sentence_lemmas = data["all_sentence_lemmas"]
    global_freq_dict    = data["global_freq_dict"]
    total_sentences     = len(sentences)

    max_view    = current_sentence if current_sentence < total_sentences else total_sentences - 1
    view_key    = f"view_sentence_{book_name}"
    slider_key  = f"slider_{book_name}"
    pending_key = f"_pending_{book_name}"

    if view_key not in st.session_state:
        st.session_state[view_key] = 0

    # if pending_key in st.session_state:
    #     target = st.session_state.pop(pending_key)
    #     target = max(0, min(target, max_view))
    #     st.session_state[view_key]   = target
    #     st.session_state[slider_key] = target
    #     st.session_state["_sentence_enter_time"][(book_name, target)] = time.time()
    if pending_key in st.session_state:
        target = st.session_state.pop(pending_key)
        # Unlock jumping forward by using total_sentences instead of max_view
        target = max(0, min(target, total_sentences - 1))
        st.session_state[view_key] = target
        st.session_state[slider_key] = target

        # Expand max_view so the slider territory unlocks properly
        if cumulative_mode:
            if target > current_sentence:
                st.session_state[book_progress_key] = target
                save_progress()
        else:
            if target > book_progress["current_sentence"]:
                book_progress["current_sentence"] = target
                save_progress()

        st.session_state["_sentence_enter_time"][(book_name, target)] = time.time()
    if st.session_state[view_key] > max_view:
        st.session_state[view_key] = max_view
    if st.session_state.get(slider_key, 0) > max_view:
        st.session_state[slider_key] = st.session_state[view_key]

    if max_view == 0:
        display_sentence = 0
    else:
        if slider_key not in st.session_state:
            st.session_state[slider_key] = st.session_state[view_key]
        st.slider("📖 Sentence selector", min_value=0, max_value=max_view,
                  step=1, key=slider_key)
        st.session_state[view_key] = st.session_state[slider_key]
        display_sentence = st.session_state[view_key]
        save_progress()

    enter_key = (book_name, display_sentence)
    if enter_key not in st.session_state["_sentence_enter_time"]:
        st.session_state["_sentence_enter_time"][enter_key] = time.time()

    if st.session_state["_pending_behavior_save"] is not None:
        append_behavior_record(username, st.session_state["_pending_behavior_save"])
        st.session_state["_pending_behavior_save"] = None

    # ── 依存数据 ──
    # dep_index 键是 (sid, lemma)，词级查询用
    # dep_by_sid 键是纯 int sid，句子级批量查询用 ← 此处使用
    dep_by_sid  = data.get("dep_by_sid", {})
    core_lemmas     = set()
    modifier_lemmas = set()
    dep_roles_by_position = {}
    dep_map_by_position   = {}

    row           = sentences[display_sentence]       # dict
    sentence_text = row.get("tokenized_sentence", "")
    sentence_id   = int(row["sentence_id"])
    sent_deps     = dep_by_sid.get(sentence_id, [])

    # sent_deps 已在上方赋值为 list of dict
    if sent_deps:
        core_rels = {"nsubj", "nsubj:pass", "obj", "iobj", "csubj", "csubj:pass", "ccomp", "xcomp", "root", "ROOT"}
        modifier_rels = {"amod", "advmod", "obl", "nmod", "appos", "acl", "acl:relcl"}

        for r in sent_deps:

            rel        = str(r.get("deprel", "")).lower()
            dep_text   = str(r.get("dependent_text", ""))
            head_text  = str(r.get("head_text", ""))
            dep_id_val = r.get("dependent_id", "")
            head_id_val= r.get("head_id", "")
            dep_clean  = re.sub(r"[^\w]", "", dep_text.lower())
            head_clean = re.sub(r"[^\w]", "", head_text.lower())
            if not dep_clean and not head_clean:
                continue
            dep_lemma  = cached_lemmatize(dep_clean)  if dep_clean  else ""
            head_lemma = cached_lemmatize(head_clean) if head_clean else ""
            try:
                dep_pos  = int(dep_id_val) - 1
                head_pos = int(head_id_val) - 1 if str(head_id_val) != '0' else -1
                if dep_pos >= 0:
                    dep_roles_by_position.setdefault(dep_pos, {'as_dependent': set(), 'as_head': set()})
                    dep_map_by_position.setdefault(dep_pos, [])
                if head_pos >= 0:
                    dep_roles_by_position.setdefault(head_pos, {'as_dependent': set(), 'as_head': set()})
                if dep_pos >= 0:
                    dep_roles_by_position[dep_pos]['as_dependent'].add(rel)
                if head_pos >= 0:
                    dep_roles_by_position[head_pos]['as_head'].add(rel)
                if dep_pos >= 0 and head_pos >= 0:
                    dep_map_by_position[dep_pos].append((head_pos, rel, head_lemma))
            except (ValueError, TypeError):
                pass
            if rel in core_rels:
                if dep_lemma:  core_lemmas.add(dep_lemma)
                if head_lemma: core_lemmas.add(head_lemma)
            elif rel in modifier_rels:
                if dep_lemma: modifier_lemmas.add(dep_lemma)

    # ── 依存距离指标 ──
    dep_dist_info = compute_dep_distances(sent_deps)

    # ── 句子简化 ──
    st.markdown("### ✂️ Sentence simplification")
    if 'simplify_mode' not in st.session_state:
        st.session_state.simplify_mode = None
    simplify_cols = st.columns(5)
    simplify_btns = [
        ("🔄 Show full sentence",           None,            f"show_all_{book_name}_{display_sentence}"),
        ("📌 Subject–Verb–Object only",      'svo_only',      f"svo_{book_name}_{display_sentence}"),
        ("🚫 Remove attributive modifiers",  'no_amod',       f"no_amod_{book_name}_{display_sentence}"),
        ("🚫 Remove adverbials",             'no_advmod',     f"no_advmod_{book_name}_{display_sentence}"),
        ("🚫 Remove complements",            'no_complement', f"no_comp_{book_name}_{display_sentence}"),
    ]
    for col, (label, mode, key) in zip(simplify_cols, simplify_btns):
        with col:
            if st.button(label, use_container_width=True, key=key):
                st.session_state.simplify_mode = mode
                st.rerun()
    mode_names = {
        None:           "Full sentence",
        'svo_only':     "Subject–Verb–Object only",
        'no_amod':      "Remove attributive modifiers",
        'no_advmod':    "Remove adverbials",
        'no_complement':"Remove complements",
    }
    st.caption(f"Current mode: {mode_names.get(st.session_state.simplify_mode, 'Full sentence')}")

    # ── [Fix-A] 构建 sentence_tokens，同时传入 dep_map_by_position ──
    sentence_tokens     = build_sentence_tokens(
        sentence_text,
        data["sentence_deltas"],
        display_sentence,
        dep_map_by_position,
        data.get("prefix_counters")  # 👈 传入缓存的预计算前缀和
    )
    sentence_word_count = len(sentence_text.split()) if sentence_text else 0

    # ── 点击日志缓存 ──
    click_cache_key = f"_click_log_cache_{book_name}_{sentence_id}"
    if click_cache_key not in st.session_state:
        st.session_state[click_cache_key] = []
    current_click_log = st.session_state[click_cache_key]

    # ── Next sentence 按钮 ──
    if current_sentence < total_sentences:
        if st.button("⏭️ Next sentence", use_container_width=True):
            leave_time = time.time()
            enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
            dwell_secs = round(leave_time - enter_time, 2)
            behavior_record = {
                "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
                "username":      username,
                "book":          book_name,
                "sentence_idx":  display_sentence,
                "sentence_id":   int(sentence_id),
                "word_count":    sentence_word_count,
                "mdd":           dep_dist_info["mdd"],
                "max_dd":        dep_dist_info["max_dd"],
                "dep_pairs":     dep_dist_info["dep_pairs"],
                "dwell_seconds": dwell_secs,
                "trigger":       "next_sentence_btn",
                "click_log":     current_click_log,
            }
            st.session_state["_pending_behavior_save"] = behavior_record
            st.session_state.pop(click_cache_key, None)
            st.session_state["_sentence_enter_time"].pop(enter_key, None)
            next_lemmas = all_sentence_lemmas[current_sentence]
            cumulative_counter.update(next_lemmas)
            if cumulative_mode:
                progress["global_counter"].update(next_lemmas)
                st.session_state[book_progress_key] = current_sentence + 1
                if current_sentence + 1 >= total_sentences:
                    if book_name not in progress["completed_books"]:
                        progress["completed_books"].append(book_name)
                    if book_name in BUILT_IN_BOOKS:
                        progress["current_book_index"] = BUILT_IN_BOOKS.index(book_name) + 1
            else:
                book_progress["current_sentence"] += 1
            st.session_state[pending_key] = min(current_sentence + 1, max_view)
            st.session_state.daily_plan["current_day_progress"] += 1
            save_progress()
            st.rerun()

    # ── 渲染交互句子 ──
    # ── 渲染双向交互句子组件 ──
    def should_show_word(word_idx):
        simplify_mode = st.session_state.get('simplify_mode')
        if simplify_mode is None:
            return True
        as_dep_rels = set()
        if word_idx in dep_roles_by_position:
            as_dep_rels = dep_roles_by_position[word_idx]['as_dependent']
        if simplify_mode == 'svo_only':
            core_rels = {'nsubj', 'nsubj:pass', 'obj', 'iobj', 'root', 'ROOT',
                         'csubj', 'csubj:pass', 'ccomp', 'xcomp'}
            return any(r in core_rels for r in as_dep_rels) or len(as_dep_rels) == 0
        elif simplify_mode == 'no_amod':
            return 'amod' not in as_dep_rels
        elif simplify_mode == 'no_advmod':
            return 'advmod' not in as_dep_rels and 'obl' not in as_dep_rels
        elif simplify_mode == 'no_complement':
            return not any(r in {'ccomp', 'xcomp', 'advcl'} for r in as_dep_rels)
        return True


    # 1. 准备传递给前端的高级 JSON 数据
    word_data_json = []
    for idx, word_data in enumerate(sentence_tokens):
        word = word_data['display']
        lemma = word_data.get('lemma')
        freq = word_data.get('freq', 0)

        if lemma and not should_show_word(idx):
            continue

        if lemma:
            color = get_color(freq)
            size_str, font = get_font_style_by_frequency(freq)
            size = int(size_str.replace('px', ''))
            styles = [f"color:{color}", f"font-size:{size}px",
                      f"font-family:{font}", "cursor:pointer"]
            if lemma in core_lemmas:     styles.append("font-weight:bold")
            if lemma in modifier_lemmas: styles.append("font-style:italic")
            style_str = "; ".join(styles)

            dep_data = []
            if 'deps_info' in word_data and word_data['deps_info']:
                for dep_item in word_data['deps_info']:
                    dep_data.append({
                        'position': dep_item.get('position'),
                        'lemma': dep_item.get('head_lemma'),
                        'deprel': dep_item.get('deprel'),
                    })
            word_data_json.append({
                'idx': idx, 'lemma': lemma, 'word': word, 'deps': dep_data,
                'style': style_str, 'clickable': True
            })
        else:
            style_str = "color:#555555; font-size:15px; font-family:Merriweather, serif"
            word_data_json.append({
                'idx': idx, 'word': word, 'style': style_str, 'clickable': False
            })

    # 2. 调用自定义组件，监听双向事件
    event = interactive_sentence_comp(
        words=word_data_json,
        deprelLabels=DEPREL_LABELS,
        sentenceId=f"{book_name}_{sentence_id}",
        simplifyMode=st.session_state.get('simplify_mode', 'full'),
        key=f"comp_{book_name}_{sentence_id}"  # key binds to current sentence
    )

    # 3. 处理前端传回来的点击交互
    if event:
        ts = event.get("ts")
        last_ts_key = f"last_ts_{book_name}_{sentence_id}"

        # Guard: Ensures we don't process the identical event twice on unrelated reruns
        if ts and st.session_state.get(last_ts_key) != ts:
            st.session_state[last_ts_key] = ts

            action = event.get("action")
            data = event.get("data", {})

            # [左键] -> 高亮 (前端已处理) + 后台记录行为日志
            if action == "left_click":
                token = next((t for t in sentence_tokens if
                              t.get('lemma') == data.get('lemma') and t.get('display') == data.get('word')), None)
                if token:
                    now = time.time()
                    last_key = f"_last_click_time_{book_name}_{sentence_id}"
                    last_click_time = st.session_state.get(last_key)
                    dwell_ms = int((now - last_click_time) * 1000) if last_click_time else 0
                    st.session_state[last_key] = now

                    ev = _build_click_event(token, dwell_ms=dwell_ms)
                    current_click_log.append(ev)
                    st.session_state[click_cache_key] = current_click_log

            # [右键] -> 后台添加生词本 + 浮动提示(Toast)不破坏页面布局
            elif action == "right_click":
                lemma = data.get('lemma')
                word = data.get('word')
                entry = {"book": book_name, "lemma": lemma, "word": word}
                if entry not in st.session_state.user_wordbook:
                    st.session_state.user_wordbook.append(entry)
                    st.toast(f"✅ Added '{word}' to the wordbook.", icon="📖")
                    save_progress()
                else:
                    st.toast(f"ℹ️ '{word}' is already in the wordbook.", icon="📌")

    # 静态提示区 (取代原来庞大的按钮网格)
    if current_click_log:
        st.caption(
            f"✅ Recorded {len(current_click_log)} clicks for this sentence: "
            f"{', '.join(dict.fromkeys(ev.get('word', '?') for ev in current_click_log))}"
        )
    else:
        st.info("No word clicks recorded yet. Left-click a word to create a log entry.")



    # ── 句子统计面板 ──
    with st.expander("📐 Sentence complexity metrics", expanded=False):
        m1, m2, m3 = st.columns(3)
        m1.metric("Word count", sentence_word_count)
        m2.metric("MDD (mean dep. distance)",
                  f"{dep_dist_info['mdd']:.2f}" if dep_dist_info['mdd'] is not None else "—")
        m3.metric("Max dep. distance",
                  dep_dist_info['max_dd'] if dep_dist_info['max_dd'] is not None else "—")

        clicked_words = sorted(set(ev.get("word", "") for ev in current_click_log if ev.get("word")))
        clicked_rels  = sorted(set(
            dep.get("deprel", "")
            for ev in current_click_log
            for dep in ev.get("deps", [])
            if dep.get("deprel")
        ))
        clicked_pairs = sorted(set(
            dep.get("pair", "")
            for ev in current_click_log
            for dep in ev.get("deps", [])
            if dep.get("pair")
        ))

        st.markdown("### Reading interaction")
        st.dataframe([{
            "Clicked Word":        ", ".join(clicked_words) if clicked_words else "—",
            "Dependency Relation": ", ".join(clicked_rels)  if clicked_rels  else "—",
            "Dependency Pair":     ", ".join(clicked_pairs) if clicked_pairs else "—",
        }], hide_index=True, use_container_width=True)

        if dep_dist_info["dep_pairs"]:
            st.markdown("**Dependency distances for each pair in this sentence:**")
            pairs_display = [{
                "dependent": p["dep_text"],
                "head":      p["head_text"],
                "relation":  p["deprel"],
                "dep_id":    p["dep_id"],
                "head_id":   p["head_id"],
                "distance":  p["distance"] if p["distance"] is not None else "root",
            } for p in dep_dist_info["dep_pairs"]]
            st.dataframe(pairs_display, use_container_width=True, hide_index=True)

    # ── TTS ──

    # ── TTS 语音朗读模块（高效磁盘缓存+极省内存版） ──
    tts_col1, _ = st.columns([1, 4])

    # 💡 优化 1：session_state 里只需要存音频文件的【路径字符串】，极省服务器内存！
    tts_path_key = f"tts_path_{book_name}_{display_sentence}"
    tts_voice = "en-US-ChristopherNeural"

    with tts_col1:
        if st.button("🔊 Play Audio", key=f"btn_tts_{book_name}_{display_sentence}"):
            with st.spinner("Generating audio..."):
                try:
                    import asyncio  # 确保顶层或这里导入了 asyncio

                    # 💡 优化 2：运行异步函数。如果是MD5缓存版，这里对于读过的句子会“秒回”本地路径
                    mp3_path = asyncio.run(do_tts(sentence_text, tts_voice))

                    # 💡 优化 3：仅将路径字符串持久化，拒绝大二进制流塞爆内存
                    st.session_state[tts_path_key] = mp3_path

                except Exception as e:
                    st.error(f"TTS generation failed: {e}")

    # 💡 优化 4：渲染音频播放器。直接把路径传给 st.audio，Streamlit 会自动在前后端高效传输
    if tts_path_key in st.session_state and st.session_state[tts_path_key]:
        st.audio(st.session_state[tts_path_key], format="audio/mp3")

    # tts_col1, _ = st.columns([1, 4])
    # with tts_col1:
    #     # if st.button("🔊 Play sentence", key=f"tts_{book_name}_{display_sentence}"):
    #     #     if sentence_text:
    #     #         audio_bytes = text_to_speech_bytes(sentence_text)
    #     #         if audio_bytes:
    #     #             st.session_state[f"tts_audio_{book_name}_{display_sentence}"] = audio_bytes
    #     #         else:
    #     #             st.warning("Speech synthesis failed.")
    #     if st.button("🔊 Play Audio"):
    #         with st.spinner("Generating audio..."):
    #             try:
    #                 # 安全地获取或运行异步任务，防止 Loop 嵌套死锁
    #                 try:
    #                     loop = asyncio.get_running_loop()
    #                 except RuntimeError:
    #                     loop = None
    #
    #                 if loop and loop.is_running():
    #                     # 如果当前线程已经在运行 loop，通过 run_coroutine_threadsafe 或 nest_asyncio 处理
    #                     # 最稳妥的降级是直接阻塞运行：
    #                     import nest_asyncio
    #
    #                     nest_asyncio.apply()
    #                     mp3_path = asyncio.run(do_tts(sentence_text, tts_voice))
    #                 else:
    #                     mp3_path = asyncio.run(do_tts(sentence_text, tts_voice))
    #
    #                 st.audio(mp3_path, format="audio/mp3")
    #             except Exception as e:
    #                 st.error(f"TTS generation failed: {e}")
    # tts_audio_key = f"tts_audio_{book_name}_{display_sentence}"
    # if tts_audio_key in st.session_state:
    #     st.audio(st.session_state[tts_audio_key], format="audio/mp3")

    # ── 加词到词汇本 ──
    if sentence_tokens:
        st.markdown("---")
        # st.markdown("**💾 Add to wordbook (click words):**")
        # valid_tokens_wb = [t for t in sentence_tokens if t.get('lemma')]
        if valid_tokens_wb:
            cols_per_row = 6
            for i in range(0, len(valid_tokens_wb), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, token in enumerate(valid_tokens_wb[i:i + cols_per_row]):
                    with cols[j]:
                        btn_key = f"add_{book_name}_{display_sentence}_{token['lemma']}_{i+j}"
                        if st.button(token['display'], key=btn_key,
                                     use_container_width=True,
                                     help=f"Click to add '{token['display']}' to the wordbook"):
                            entry = {"book": book_name,
                                     "lemma": token['lemma'],
                                     "word":  token['display']}
                            if entry not in st.session_state.user_wordbook:
                                st.session_state.user_wordbook.append(entry)
                                st.success(f"✅ Added '{token['display']}' to the wordbook.")
                                save_progress()
                            else:
                                st.info(f"'{token['display']}' is already in the wordbook.")

    st.caption(
        f"Viewing sentence {display_sentence + 1} / {total_sentences} "
        f"| Progressed to sentence {current_sentence + 1}")

    # ── 社交分享 ──
    st.markdown("---")

    def parse_book_title_author(book_stem: str):
        name      = re.sub(r'^\d+_', '', book_stem).replace('_', ' ')
        words_lst = name.split()
        stop_words = {'of', 'the', 'a', 'an', 'and', 'in', 'to', 'by'}
        author_words = []
        i = len(words_lst) - 1
        while (i >= 0 and words_lst[i][0].isupper()
               and words_lst[i].lower() not in stop_words):
            author_words.insert(0, words_lst[i])
            i -= 1
        if len(author_words) == len(words_lst) or len(author_words) == 0:
            mid    = len(words_lst) // 2
            title  = ' '.join(words_lst[:mid]) if mid > 0 else name
            author = ' '.join(words_lst[mid:]) if mid < len(words_lst) else ''
        else:
            title  = ' '.join(words_lst[:i + 1])
            author = ' '.join(author_words)
        return title.strip() or name, author.strip()

    def generate_share_html(book_stem, disp_sent, total_sents, sent_text):
        title, author = parse_book_title_author(book_stem)
        display_text  = sent_text if len(sent_text) <= 200 else sent_text[:197] + '…'
        sentence_num  = disp_sent + 1
        js_params     = json.dumps({
            "title": title, "author": author,
            "sentence_num": sentence_num, "total": total_sents, "text": display_text,
        })
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,400&family=Crimson+Pro:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@300;400&display=swap" rel="stylesheet">
<style>
:root{{--ink:#1a1209;--gold:#c8922a;--gold2:#f0c060;--cream:#f7f0e3;--paper:#fdf8ef;--muted:#8a7a62;--border:#ddd0b8;}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Crimson Pro',Georgia,serif;background:var(--paper);display:flex;flex-direction:column;align-items:center;padding:20px 16px 32px;}}
.card{{width:100%;max-width:640px;background:#fffdf7;border:1px solid var(--border);border-radius:4px;box-shadow:0 2px 4px rgba(30,18,5,.12),0 10px 32px rgba(30,18,5,.09);overflow:hidden;}}
.card-topbar{{height:4px;background:linear-gradient(90deg,var(--gold),var(--gold2),var(--gold));}}
.card-body{{padding:28px 36px 24px;}}
.book-title{{font-family:'Playfair Display',serif;font-size:20px;font-weight:700;color:var(--ink);line-height:1.2;}}
.book-author{{font-family:'Crimson Pro',serif;font-style:italic;font-size:14px;color:var(--muted);margin-top:2px;}}
.sentence-text{{font-family:'Playfair Display',serif;font-size:17px;font-style:italic;line-height:1.75;color:var(--ink);padding:20px 0 10px;}}
.card-footer{{padding:12px 36px 16px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}}
.brand{{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;color:var(--muted);}}
.brand b{{color:var(--gold);}}
.share-section{{width:100%;max-width:640px;margin-top:20px;}}
.btn-primary-row{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;}}
.btn-primary{{display:flex;align-items:center;justify-content:center;gap:7px;padding:12px;border:none;border-radius:3px;background:var(--ink);color:var(--cream);font-family:'JetBrains Mono',monospace;font-size:11px;cursor:pointer;}}
.btn-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:6px;}}
.plat-btn{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:10px 4px 8px;border:1px solid var(--border);border-radius:3px;background:#fffdf7;cursor:pointer;font-size:18px;}}
.plat-btn span{{font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--muted);text-align:center;}}
.copy-bar{{display:flex;align-items:center;gap:8px;background:white;border:1px solid var(--border);border-radius:3px;padding:8px 12px;margin-top:8px;}}
.copy-preview{{flex:1;font-family:'Crimson Pro',serif;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.copy-mini-btn{{background:none;border:1px solid var(--border);border-radius:2px;padding:3px 9px;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);cursor:pointer;}}
canvas{{display:none;}}
</style></head><body>
<div class="card"><div class="card-topbar"></div><div class="card-body">
<div class="book-title" id="bt"></div><div class="book-author" id="ba"></div>
<div style="font-size:28px;font-weight:900;color:var(--gold);margin:8px 0" id="pn"></div>
<div class="sentence-text" id="st2"></div></div>
<div class="card-footer"><div class="brand"><b>English Reader</b> &middot; Classic Novels</div></div></div>
<canvas id="cv" width="680" height="400"></canvas>
<div class="share-section">
<div class="btn-primary-row">
<button class="btn-primary" onclick="downloadImg()">⬇ Save Image</button>
<button class="btn-primary" onclick="copyText()" id="cmb">📋 Copy Text</button></div>
<div class="btn-grid">
<button class="plat-btn" onclick="shareTwitter()">𝕏<span>Twitter</span></button>
<button class="plat-btn" onclick="shareFacebook()">f<span>Facebook</span></button>
<button class="plat-btn" onclick="shareThreads()">@<span>Threads</span></button>
<button class="plat-btn" onclick="shareLinkedIn()">in<span>LinkedIn</span></button>
<button class="plat-btn" onclick="shareWhatsApp()">💬<span>WhatsApp</span></button>
<button class="plat-btn" onclick="shareTelegram()">✈️<span>Telegram</span></button>
<button class="plat-btn" onclick="shareReddit()">🤖<span>Reddit</span></button>
<button class="plat-btn" onclick="sharePinterest()">📌<span>Pinterest</span></button>
<button class="plat-btn" onclick="shareInstagram()">📷<span>Instagram</span></button>
<button class="plat-btn" onclick="shareTikTok()">♪<span>TikTok</span></button></div>
<div class="copy-bar"><div class="copy-preview" id="cp2"></div>
<button class="copy-mini-btn" onclick="copyText2()">COPY</button></div></div>
<script>
const P={js_params};
document.getElementById('bt').textContent=P.title;
document.getElementById('ba').textContent=P.author?'— '+P.author:'';
document.getElementById('pn').textContent='Sentence '+P.sentence_num+' / '+P.total;
document.getElementById('st2').textContent=P.text;
document.getElementById('cp2').textContent='📖 "'+P.title+'" · S'+P.sentence_num+'/'+P.total+' — "'+P.text.slice(0,80)+'" #EnglishReader';
function shareText(){{return `📖 I'm reading "${{P.title}}"${{P.author?' by '+P.author:''}} — Sentence ${{P.sentence_num}}/${{P.total}}\\n\\n"${{P.text}}"\\n\\n#EnglishReader #ClassicNovels`;}}
function shareTwitter(){{window.open('https://twitter.com/intent/tweet?text='+encodeURIComponent(shareText()),'_blank');}}
function shareFacebook(){{window.open('https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(location.href)+'&quote='+encodeURIComponent(shareText()),'_blank');}}
function shareThreads(){{window.open('https://www.threads.net/intent/post?text='+encodeURIComponent(shareText()),'_blank');}}
function shareLinkedIn(){{window.open('https://www.linkedin.com/sharing/share-offsite/?url='+encodeURIComponent(location.href),'_blank');}}
function shareWhatsApp(){{window.open('https://wa.me/?text='+encodeURIComponent(shareText()),'_blank');}}
function shareTelegram(){{window.open('https://t.me/share/url?url='+encodeURIComponent(location.href)+'&text='+encodeURIComponent(shareText()),'_blank');}}
function shareReddit(){{window.open('https://www.reddit.com/submit?title='+encodeURIComponent('Reading: '+P.title)+'&text='+encodeURIComponent(shareText()),'_blank');}}
function sharePinterest(){{window.open('https://pinterest.com/pin/create/button/?description='+encodeURIComponent(shareText()),'_blank');}}
function shareInstagram(){{copyText();alert('Text copied! Open Instagram and paste.');}}
function shareTikTok(){{copyText();alert('Text copied! Open TikTok and paste.');}}
function drawCard(){{
  const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),W=cv.width,H=cv.height;
  ctx.fillStyle='#fffdf7';ctx.fillRect(0,0,W,H);
  const g=ctx.createLinearGradient(0,0,W,0);g.addColorStop(0,'#c8922a');g.addColorStop(.5,'#f0c060');g.addColorStop(1,'#c8922a');
  ctx.fillStyle=g;ctx.fillRect(0,0,W,5);
  ctx.fillStyle='#1a1209';ctx.font='bold 22px Georgia,serif';ctx.textAlign='left';
  ctx.fillText(P.title.length>48?P.title.slice(0,46)+'…':P.title,40,48);
  ctx.fillStyle='#8a7a62';ctx.font='italic 14px Georgia,serif';ctx.fillText(P.author?'— '+P.author:'',42,68);
  ctx.fillStyle='#c8922a';ctx.font='bold 34px Georgia,serif';ctx.textAlign='right';ctx.fillText(String(P.sentence_num),W-40,50);
  ctx.fillStyle='#8a7a62';ctx.font='11px "Courier New",monospace';ctx.fillText('of '+P.total.toLocaleString()+' sentences',W-40,68);
  ctx.fillStyle='#ddd0b8';ctx.fillRect(40,82,W-80,3);
  const pg=ctx.createLinearGradient(40,0,W-40,0);pg.addColorStop(0,'#c8922a');pg.addColorStop(1,'#f0c060');
  ctx.fillStyle=pg;ctx.fillRect(40,82,(W-80)*Math.min(P.sentence_num/P.total,1),3);
  ctx.strokeStyle='#ddd0b8';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(40,100);ctx.lineTo(W-40,100);ctx.stroke();
  ctx.fillStyle='rgba(240,192,96,.28)';ctx.font='bold 72px Georgia,serif';ctx.textAlign='left';ctx.fillText('\u201c',28,168);
  ctx.fillStyle='#1a1209';ctx.font='italic 17px Georgia,serif';
  const ws=P.text.split(' ');let ln='',ly=130,lh=26,lc=0;
  for(let i=0;i<ws.length;i++){{const t=ln+(ln?' ':'')+ws[i];if(ctx.measureText(t).width>W-100&&ln){{if(lc>=6){{ctx.fillText(ln+(i<ws.length-1?' …':''),52,ly);break;}}ctx.fillText(ln,52,ly);ln=ws[i];ly+=lh;lc++;}}else ln=t;}}
  if(lc<7&&ln)ctx.fillText(ln,52,ly);
  ctx.beginPath();ctx.moveTo(40,H-44);ctx.lineTo(W-40,H-44);ctx.stroke();
  ctx.fillStyle='#8a7a62';ctx.font='10px "Courier New",monospace';ctx.textAlign='left';ctx.fillText('ENGLISH READER · CLASSIC NOVELS',40,H-20);
  ctx.textAlign='right';ctx.fillText('englishreader.app',W-40,H-20);
  ctx.fillStyle=g;ctx.fillRect(0,H-4,W,4);}}
function downloadImg(){{drawCard();const a=document.createElement('a');a.href=document.getElementById('cv').toDataURL('image/png');a.download='reading_s'+P.sentence_num+'.png';a.click();}}
function _doCopy(){{const t=shareText();if(navigator.clipboard)navigator.clipboard.writeText(t);else{{const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);}}}}
function copyText(){{_doCopy();const b=document.getElementById('cmb');b.textContent='✅ Copied!';setTimeout(()=>b.textContent='📋 Copy Text',2000);}}
function copyText2(){{_doCopy();}}
</script></body></html>"""

    share_key = f"show_share_{book_name}_{display_sentence}"
    if share_key not in st.session_state:
        st.session_state[share_key] = False
    if st.button(
        "📤 Share reading progress" if not st.session_state[share_key]
        else "✖️ Close share panel",
        key=f"share_toggle_{book_name}_{display_sentence}"):
        st.session_state[share_key] = not st.session_state[share_key]
        st.rerun()
    if st.session_state[share_key]:
        components.html(
            generate_share_html(book_name, display_sentence, total_sentences, sentence_text),
            height=780, scrolling=False)

    # ── 单词查询 ──
    query_word = st.text_input("🔍 Enter a word to look up")
    if query_word:
        # 移除不存在的 lemmatizer 调用，做安全的字符串清洗
        lemma_query = query_word.strip().lower()
        phonetic, audio_url, explanation = get_word_info(query_word)
        #lemma_query          = lemmatizer.lemmatize(query_word.lower())
        #phonetic, audio_url, explanation = get_word_info(query_word)
        st.write(f"**Word:** {query_word}")
        st.write(f"**Lemma:** {lemma_query}")
        st.write(f"**Phonetic:** {phonetic}")
        if audio_url:
            try:
                st.audio(BytesIO(requests.get(audio_url, timeout=5).content),
                         format="audio/mp3")
            except Exception:
                pass
        st.write(f"**Definition:** {explanation}")

    # ── 依存分析 ──
    dep_key = f"show_dep_{book_name}_{display_sentence}"
    if dep_key not in st.session_state:
        st.session_state[dep_key] = False
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            "🔍 Show dependency analysis" if not st.session_state[dep_key]
            else "❌ Hide dependency analysis",
            key=f"dep_toggle_{book_name}_{display_sentence}"):
            st.session_state[dep_key] = not st.session_state[dep_key]
            st.rerun()
    if st.session_state[dep_key]:
        sent_deps_show = data.get("dep_by_sid", {}).get(sentence_id, [])
        if sent_deps_show:
            st.subheader("Dependency relations")
            for r in sent_deps_show:
                head = str(r.get('head_text', ''))
                dep  = str(r.get('dependent_text', ''))
                rel  = str(r.get('deprel', ''))
                if head not in ['', 'nan'] and dep not in ['', 'nan']:
                    st.text(f"{head} ──{rel}──> {dep}")
        else:
            st.info("No dependency records for this sentence.")

    if GRAPHVIZ_AVAILABLE:
        tree_key = f"show_tree_{book_name}_{display_sentence}"
        if tree_key not in st.session_state:
            st.session_state[tree_key] = False
        with col2:
            if st.button(
                "🌳 Show dependency tree" if not st.session_state[tree_key]
                else "❌ Hide dependency tree",
                key=f"tree_toggle_{book_name}_{display_sentence}"):
                st.session_state[tree_key] = not st.session_state[tree_key]
                st.rerun()
        if st.session_state[tree_key]:
            arc_html = generate_dep_arc_html(data["dep_rows"], sentence_id)
            if arc_html:
                components.html(arc_html, height=420, scrolling=False)
            else:
                st.info("Unable to generate dependency tree.")

    # ── Prev / Next 按钮 ──
    # ── 🎯 完美集成跳读功能的进度控制面板（日志行为完备版） ──
    # 使用 4 列紧凑排版：上一句按钮、跳读数字输入框、进度百分比展示、下一句按钮
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1, 1.5, 1.5, 1])

    with ctrl_col1:
        if display_sentence > 0:
            if st.button("← Previous", key=f"prev_btn_v3_{book_name}_{display_sentence}", use_container_width=True):
                leave_time = time.time()
                enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
                dwell_secs = round(leave_time - enter_time, 2)
                behavior_record = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "username": username,
                    "book": book_name,
                    "sentence_idx": display_sentence,
                    "sentence_id": int(sentence_id),
                    "word_count": sentence_word_count,
                    "mdd": dep_dist_info["mdd"],
                    "max_dd": dep_dist_info["max_dd"],
                    "dep_pairs": dep_dist_info["dep_pairs"],
                    "dwell_seconds": dwell_secs,
                    "trigger": "prev_btn",  # 保持原有行为标记
                    "click_log": current_click_log,
                }
                st.session_state["_pending_behavior_save"] = behavior_record
                st.session_state.pop(click_cache_key, None)
                st.session_state["_sentence_enter_time"].pop(enter_key, None)
                st.session_state[pending_key] = display_sentence - 1
                save_progress()
                st.rerun()

    # with ctrl_col2:
    #     # ✨ 【核心新增：跳读输入框】
    #     # 显示给用户 1-based (从 1 开始的序号)，后台自动转换对齐到 0-based 数组
    #     max_valid_idx = int(total_sentences)
    #     display_idx = display_sentence + 1
    #
    #     target_sentence_1based = st.number_input(
    #         label="🎯 Jump to Sentence:",
    #         min_value=1,
    #         max_value=max_valid_idx,
    #         value=int(display_idx),
    #         step=1,
    #         label_visibility="collapsed",  # 隐藏上方的多余提示文字，保持排版精简
    #         key=f"jump_input_{book_name}"  # ← key 不含 display_sentence，避免每次跳转后 key 变化导致组件重置死循环
    #     )
    #
    #     # 💡 联动监听：如果用户输入的页码发生了改变（代表敲击了回车或按了加减）
    #     target_sentence_0based = target_sentence_1based - 1
    #     if target_sentence_0based != display_sentence:
    #         leave_time = time.time()
    #         enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
    #         dwell_secs = round(leave_time - enter_time, 2)
    #
    #         # ⚡ 完美融入：跳读时也生成一条对应的行为日志，并将 trigger 标记为 "jump_input"
    #         behavior_record = {
    #             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    #             "username": username,
    #             "book": book_name,
    #             "sentence_idx": display_sentence,
    #             "sentence_id": int(sentence_id),
    #             "word_count": sentence_word_count,
    #             "mdd": dep_dist_info["mdd"],
    #             "max_dd": dep_dist_info["max_dd"],
    #             "dep_pairs": dep_dist_info["dep_pairs"],
    #             "dwell_seconds": dwell_secs,
    #             "trigger": f"jump_to_{target_sentence_1based}",  # 动态记录跳读目标，极其利于后续科研行为分析
    #             "click_log": current_click_log,
    #         }
    #         st.session_state["_pending_behavior_save"] = behavior_record
    #         st.session_state.pop(click_cache_key, None)
    #         st.session_state["_sentence_enter_time"].pop(enter_key, None)
    #
    #         # 变更进度指针并保存刷新
    #         st.session_state[pending_key] = target_sentence_0based
    #         save_progress()
    #         st.rerun()
        # Define callback right above the columns to handle jump input cleanly
        def on_jump_input():
            st.session_state["_pending_jump_target"] = st.session_state[f"jump_input_{book_name}"] - 1


    with ctrl_col2:
        # ✨ 【核心新增：跳读输入框】
        max_valid_idx = int(total_sentences)
        display_idx = display_sentence + 1
        jump_key = f"jump_input_{book_name}"

        # 1. Process pending jump triggered by the callback
        if "_pending_jump_target" in st.session_state:
            target_sentence_0based = st.session_state.pop("_pending_jump_target")
            if target_sentence_0based != display_sentence:
                leave_time = time.time()
                enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
                dwell_secs = round(leave_time - enter_time, 2)

                # ⚡ 完美融入：跳读时也生成一条对应的行为日志
                behavior_record = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "username": username,
                    "book": book_name,
                    "sentence_idx": display_sentence,
                    "sentence_id": int(sentence_id),
                    "word_count": sentence_word_count,
                    "mdd": dep_dist_info["mdd"],
                    "max_dd": dep_dist_info["max_dd"],
                    "dep_pairs": dep_dist_info["dep_pairs"],
                    "dwell_seconds": dwell_secs,
                    "trigger": f"jump_to_{target_sentence_0based + 1}",
                    "click_log": current_click_log,
                }
                st.session_state["_pending_behavior_save"] = behavior_record
                st.session_state.pop(click_cache_key, None)
                st.session_state["_sentence_enter_time"].pop(enter_key, None)

                st.session_state[pending_key] = target_sentence_0based
                save_progress()
                st.rerun()

        # 2. Prevent widget state desync when display_idx is changed externally (e.g. Next/Prev/Slider)
        if jump_key not in st.session_state or st.session_state[jump_key] != display_idx:
            st.session_state[jump_key] = int(display_idx)

        target_sentence_1based = st.number_input(
            label="🎯 Jump to Sentence:",
            min_value=1,
            max_value=max_valid_idx,
            step=1,
            label_visibility="collapsed",
            key=jump_key,
            on_change=on_jump_input
        )
    with ctrl_col3:
        # 在中间两列之间，优雅地居中打印当前进度百分比
        progress_pct = ((display_sentence + 1) / total_sentences) * 100
        st.markdown(
            f"<div style='text-align: center; line-height: 38px; color: #555; font-size: 14px;'>"
            f"<b>{display_sentence + 1}</b> / {total_sentences} ({progress_pct:.1f}%)"
            f"</div>",
            unsafe_allow_html=True
        )

    with ctrl_col4:
        if display_sentence < max_view:
            if st.button("Next →", key=f"next_btn_v3_{book_name}_{display_sentence}", use_container_width=True):
                leave_time = time.time()
                enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
                dwell_secs = round(leave_time - enter_time, 2)
                behavior_record = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "username": username,
                    "book": book_name,
                    "sentence_idx": display_sentence,
                    "sentence_id": int(sentence_id),
                    "word_count": sentence_word_count,
                    "mdd": dep_dist_info["mdd"],
                    "max_dd": dep_dist_info["max_dd"],
                    "dep_pairs": dep_dist_info["dep_pairs"],
                    "dwell_seconds": dwell_secs,
                    "trigger": "next_view_btn",
                    "click_log": current_click_log,
                }
                st.session_state["_pending_behavior_save"] = behavior_record
                st.session_state.pop(click_cache_key, None)
                st.session_state["_sentence_enter_time"].pop(enter_key, None)
                st.session_state[pending_key] = display_sentence + 1
                save_progress()
                st.rerun()
    # col_prev, col_next = st.columns([1, 1])
    # with col_prev:
    #     if display_sentence > 0:
    #         if st.button("← Previous sentence",
    #                      key=f"prev_btn_{book_name}_{display_sentence}"):
    #             leave_time = time.time()
    #             enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
    #             dwell_secs = round(leave_time - enter_time, 2)
    #             behavior_record = {
    #                 "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
    #                 "username":      username,
    #                 "book":          book_name,
    #                 "sentence_idx":  display_sentence,
    #                 "sentence_id":   int(sentence_id),
    #                 "word_count":    sentence_word_count,
    #                 "mdd":           dep_dist_info["mdd"],
    #                 "max_dd":        dep_dist_info["max_dd"],
    #                 "dep_pairs":     dep_dist_info["dep_pairs"],
    #                 "dwell_seconds": dwell_secs,
    #                 "trigger":       "prev_btn",
    #                 "click_log":     current_click_log,
    #             }
    #             st.session_state["_pending_behavior_save"] = behavior_record
    #             st.session_state.pop(click_cache_key, None)
    #             st.session_state["_sentence_enter_time"].pop(enter_key, None)
    #             st.session_state[pending_key] = display_sentence - 1
    #             save_progress()
    #             st.rerun()
    #
    # with col_next:
    #     if display_sentence < max_view:
    #         if st.button("Next sentence →",
    #                      key=f"next_btn_{book_name}_{display_sentence}"):
    #             leave_time = time.time()
    #             enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
    #             dwell_secs = round(leave_time - enter_time, 2)
    #             behavior_record = {
    #                 "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
    #                 "username":      username,
    #                 "book":          book_name,
    #                 "sentence_idx":  display_sentence,
    #                 "sentence_id":   int(sentence_id),
    #                 "word_count":    sentence_word_count,
    #                 "mdd":           dep_dist_info["mdd"],
    #                 "max_dd":        dep_dist_info["max_dd"],
    #                 "dep_pairs":     dep_dist_info["dep_pairs"],
    #                 "dwell_seconds": dwell_secs,
    #                 "trigger":       "next_view_btn",
    #                 "click_log":     current_click_log,
    #             }
    #             st.session_state["_pending_behavior_save"] = behavior_record
    #             st.session_state.pop(click_cache_key, None)
    #             st.session_state["_sentence_enter_time"].pop(enter_key, None)
    #             st.session_state[pending_key] = display_sentence + 1
    #             save_progress()
    #             st.rerun()


# ===================================================================
# TAB 2 ── WORDBOOK
# ===================================================================
with tab2:
    st.title("📚 Wordbook")
    wordbook = st.session_state.user_wordbook
    normalized_wordbook = []
    for item in wordbook:
        if isinstance(item, dict):
            normalized_wordbook.append(item)
        elif isinstance(item, str):
            normalized_wordbook.append(
                {"book": "unknown", "lemma": item.lower(), "word": item})
    if normalized_wordbook != wordbook:
        st.session_state.user_wordbook = normalized_wordbook
    wordbook = normalized_wordbook

    if not wordbook:
        st.info("The wordbook is empty. Add words from the reading tab.")
    else:
        current_book_words = [w for w in wordbook if w.get("book") == book_name]
        if not current_book_words:
            st.info("This book has no saved words yet. Add words from the reading tab.")
        else:
            lemma_to_word = {}
            for w in current_book_words:
                lemma = w.get("lemma")
                if lemma and lemma not in lemma_to_word:
                    lemma_to_word[lemma] = w.get("word", lemma)
            sorted_lemmas = sorted(lemma_to_word.keys())
            selected_lemma = st.selectbox(
                "Select a word to view example sentences in this book",
                options=sorted_lemmas,
                format_func=lambda x: f"{lemma_to_word.get(x, x)} ({x})")

            if selected_lemma:
                sentences_for_word = get_word_sentences(
                    selected_lemma, sentences, all_sentence_lemmas)
                if not sentences_for_word:
                    st.info("No sentences containing this word were found in this book.")
                else:
                    sentences_for_word.sort(key=lambda x: x["sentence_id"])
                    total_hits = len(sentences_for_word)
                    st.markdown(
                        f"**Found {total_hits} sentences containing this word "
                        f"(ordered by sentence index)**")
                    top_n = 5
                    for item in sentences_for_word[:top_n]:
                        st.write(f"{item['sentence_id']}: {item['text']}")
                    if total_hits > top_n:
                        with st.expander(f"Show remaining {total_hits - top_n} sentences"):
                            for item in sentences_for_word[top_n:]:
                                st.write(f"{item['sentence_id']}: {item['text']}")

                st.markdown("---")
                st.subheader("🔗 Word dependencies and definitions")
                default_query = lemma_to_word.get(selected_lemma, selected_lemma)
                dep_query = st.text_input(
                    "Enter a word (view dependencies & definition)",
                    value=default_query,
                    key=f"dep_query_input_{book_name}")

                if st.button("🔍 Show word dependencies", key=f"dep_btn_{book_name}"):
                    if not dep_query:
                        st.warning("Please enter a word first.")
                    else:
                        # ── ⚡ 适配修改 1：移除 lemmatizer，直接转为标准小写 ──
                        lemma_dep = dep_query.strip().lower()
                        dep_rows_all = data.get("dep_rows", [])
                        matched_deps = [
                            r for r in dep_rows_all
                            if r.get("dependent_lemma", "").lower() == lemma_dep
                            or r.get("head_lemma", "").lower() == lemma_dep
                        ]
                        matched_deps.sort(key=lambda r: int(r.get("sentence_id", 0)))

                        if matched_deps:
                            st.subheader("Dependency relations (ordered by sentence index)")
                            current_sid = int(sentences[display_sentence]["sentence_id"])
                            shown = 0
                            for row in matched_deps:
                                if shown >= 200:
                                    break
                                sid = int(row["sentence_id"])
                                relation = f"[{row['dependent_text']}] --({row['deprel']})--> [{row['head_text']}]"
                                if sid == current_sid:
                                    st.markdown(f"**★ [{sid}]** `{relation}`")
                                else:
                                    st.text(f"[{sid}] {relation}")
                                shown += 1
                            if len(matched_deps) > 200:
                                st.info(f"{len(matched_deps)} relations in total, showing the first 200.")
                        else:
                            st.info("No dependency relations found for this word.")
# with tab2:
#     st.title("📚 Wordbook")
#     wordbook = st.session_state.user_wordbook
#     normalized_wordbook = []
#     for item in wordbook:
#         if isinstance(item, dict):
#             normalized_wordbook.append(item)
#         elif isinstance(item, str):
#             normalized_wordbook.append(
#                 {"book": "unknown", "lemma": item.lower(), "word": item})
#     if normalized_wordbook != wordbook:
#         st.session_state.user_wordbook = normalized_wordbook
#     wordbook = normalized_wordbook
#
#     if not wordbook:
#         st.info("The wordbook is empty. Add words from the reading tab.")
#     else:
#         current_book_words = [w for w in wordbook if w.get("book") == book_name]
#         if not current_book_words:
#             st.info("This book has no saved words yet. Add words from the reading tab.")
#         else:
#             lemma_to_word = {}
#             for w in current_book_words:
#                 lemma = w.get("lemma")
#                 if lemma and lemma not in lemma_to_word:
#                     lemma_to_word[lemma] = w.get("word", lemma)
#             sorted_lemmas  = sorted(lemma_to_word.keys())
#             selected_lemma = st.selectbox(
#                 "Select a word to view example sentences in this book",
#                 options=sorted_lemmas,
#                 format_func=lambda x: f"{lemma_to_word.get(x, x)} ({x})")
#             if selected_lemma:
#                 sentences_for_word = get_word_sentences(
#                     selected_lemma, sentences, all_sentence_lemmas)
#                 if not sentences_for_word:
#                     st.info("No sentences containing this word were found in this book.")
#                 else:
#                     sentences_for_word.sort(key=lambda x: x["sentence_id"])
#                     total_hits = len(sentences_for_word)
#                     st.markdown(
#                         f"**Found {total_hits} sentences containing this word "
#                         f"(ordered by sentence index)**")
#                     top_n = 5
#                     for item in sentences_for_word[:top_n]:
#                         st.write(f"{item['sentence_id']}: {item['text']}")
#                     if total_hits > top_n:
#                         with st.expander(f"Show remaining {total_hits - top_n} sentences"):
#                             for item in sentences_for_word[top_n:]:
#                                 st.write(f"{item['sentence_id']}: {item['text']}")
#                 st.markdown("---")
#                 st.subheader("🔗 Word dependencies and definitions")
#                 default_query = lemma_to_word.get(selected_lemma, selected_lemma)
#                 dep_query = st.text_input(
#                     "Enter a word (view dependencies & definition)",
#                     value=default_query,
#                     key=f"dep_query_input_{book_name}")
#                 if st.button("🔍 Show word dependencies", key=f"dep_btn_{book_name}"):
#                     if not dep_query:
#                         st.warning("Please enter a word first.")
#                     else:
#                         lemma_dep = lemmatizer.lemmatize(dep_query.lower())
#                         dep_pairs = get_word_dependencies(lemma_dep, data["dep_df"])
#                         if dep_pairs:
#                             st.subheader(
#                                 "Dependency relations (ordered by sentence index)")
#                             current_sid = sentences_df.iloc[display_sentence]["sentence_id"]
#                             shown = 0
#                             for pair in dep_pairs:
#                                 if shown >= 200: break
#                                 sid      = pair['sentence_id']
#                                 relation = pair['relation']
#                                 if sid == current_sid:
#                                     st.markdown(f"**★ [{sid}]** `{relation}`")
#                                 else:
#                                     st.text(f"[{sid}] {relation}")
#                                 shown += 1
#                             if len(dep_pairs) > 200:
#                                 st.info(
#                                     f"{len(dep_pairs)} relations in total, "
#                                     f"showing the first 200.")
#                         else:
#                             st.info(
#                                 "No dependency relations found for this word.")
#

# ===================================================================
# TAB 3 ── VOCABULARY UNIVERSE
# ===================================================================
with tab3:
    st.title("🌌 Vocabulary universe")

    # ── 1. 安全提取动态阅读词频计数器 ──
    if cumulative_mode:
        user_seen_counter = progress.get("global_counter", Counter())
    else:
        # 增加极其严格的边界防御，防止 Rerun 时 current_sentence 越界导致 App 白屏
        prefix_counters = data.get("prefix_counters", [])
        sentence_deltas = data.get("sentence_deltas", [])

        if prefix_counters and sentence_deltas and current_sentence < len(prefix_counters):
            try:
                user_seen_counter = prefix_counters[current_sentence].copy()
                if current_sentence < len(sentence_deltas):
                    user_seen_counter.update(sentence_deltas[current_sentence])
            except Exception:
                user_seen_counter = Counter()
        else:
            user_seen_counter = Counter()

    # 获取标准词汇分级表
    standard_wordlists = st.session_state.get("standard_wordlists", {})

    # ── 2. 动态词汇覆盖率统计（增强鲁棒性版） ──
    if user_seen_counter and standard_wordlists:
        # 清洗逻辑：去空格、转小写，但【放宽限制】，不要用 isalpha() 过滤，防止特殊标点导致和依存数据脱节
        text_lemmas = {
            str(k).lower().strip()
            for k in user_seen_counter.keys()
            if str(k).strip()
        }

        st.markdown("### 📈 Vocabulary coverage statistics (Current Progress)")
        stats_cols = st.columns(4)

        # 提取全书的所有词根，做安全兜底
        global_freq = data.get("global_freq_dict", {})
        book_lemmas = {str(k).lower().strip() for k in global_freq.keys() if str(k).strip()}

        for idx, (level, wl_set) in enumerate(sorted(standard_wordlists.items())):
            if idx >= 4:
                break

            # 确保 wl_set 是标准的 set 集合（防御第一段传递 DataFrame 的历史遗留 Bug）
            if isinstance(wl_set, dict):
                wordlist_lemmas = set(wl_set.keys())
            elif isinstance(wl_set, set):
                wordlist_lemmas = wl_set
            else:
                # 如果依然是 DataFrame，进行紧急转换防护
                try:
                    wordlist_lemmas = set(wl_set['lemma'].str.lower())
                except Exception:
                    wordlist_lemmas = set()

            # 计算交集
            intersection = text_lemmas & wordlist_lemmas
            book_in_coca = book_lemmas & wordlist_lemmas

            # 计算覆盖率
            coverage = (len(intersection) / len(book_in_coca) * 100 if book_in_coca else 0)

            with stats_cols[idx]:
                st.metric(
                    label=f"COCA {(level - 1) * 5000 + 1}-{level * 5000}",
                    value=f"{len(intersection)} words",
                    delta=f"{coverage:.1f}% coverage"
                )
    else:
        st.info("💡 Start reading sentences in TAB 1 to generate your real-time vocabulary metrics!")

    # ── 📊 图表联动区域 ──
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("📊 Show dependency relation types", key="btn_show_deprels"):
            # 确保数据源存在且不为空
            dep_rows_tab3 = data.get("dep_rows", [])
            if dep_rows_tab3:
                from collections import Counter as _C
                deprel_counts = _C(r.get("deprel", "") for r in dep_rows_tab3)
                labels = list(deprel_counts.keys())
                values = list(deprel_counts.values())
                fig = px.bar(
                    x=labels, y=values,
                    labels={"x": "Dependency Relation (deprel)", "y": "Count"},
                    title="Distribution of Dependency Relation Types in Current Book",
                    color_discrete_sequence=["#1976D2"]
                )
                fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No dependency data available for this book.")

    with col2:
        if st.button("📋 Show word frequency table", key="btn_show_freq_table"):
            if user_seen_counter:
                # ── ⚡ 核心对齐修改 2：用用户当前的动态词频字典直接渲染，提速百倍 ──
                # 将内存字典瞬间转为 DataFrame，避免任何多余的 NLTK 实时处理
                def _wl_order(wl):
                    # 解析 "COCA 1-5000" 格式，取起始数字排序
                    if "COCA" in str(wl):
                        try: return int(str(wl).split()[1].split("-")[0])
                        except Exception: pass
                    return 999999

                rows_freq = []
                for lemma_key, freq_val in user_seen_counter.items():
                    wl_label = "Unknown"
                    for level, wl_set in sorted(standard_wordlists.items()):
                        if str(lemma_key).lower() in wl_set:
                            wl_label = f"COCA {(level-1)*5000+1}-{level*5000}"
                            break
                    rows_freq.append({"lemma": lemma_key, "frequency": freq_val, "wordlist": wl_label})

                rows_freq.sort(key=lambda r: (_wl_order(r["wordlist"]), -r["frequency"]))
                st.dataframe(rows_freq, use_container_width=True, hide_index=True)
            else:
                st.info("Your dynamic word frequency table is empty. Read some sentences first!")
# with tab3:
#     st.title("🌌 Vocabulary universe")
#
#     counter_for_stats = (progress["global_counter"]
#                          if cumulative_mode else cumulative_counter)
#
#     # 从 Session State 获取官方的标准词汇分级表（COCA等）
#     standard_wordlists = st.session_state.get("standard_wordlists", {})
#
#     # ── ⚡ 适配修改 1：原 data["wordlist"] 降级兼容或替换为预计算的 lemma_pos_df ──
#     # 在新数据结构中，我们将通过 lemma_positions 提取全书不重复的单词表
#     lemma_pos_df = data.get("sentences", pd.DataFrame())  # 兜底逻辑
#     if "lemma_pos_df" in data:
#         lemma_pos_df = data["lemma_pos_df"]
#     elif "sentences" in data and hasattr(data, "get"):
#         # 兼容层：如果之前组装时直接叫原始表，或者我们可以直接通过大表去重
#         # 根据我们在 data_loader 里的组装，这里我们可以直接通过下面的方式提取唯一 Lemma 表
#         pass
#
#     # 最佳实践：直接从 `global_freq_dict` 瞬间生成唯一词汇表，彻底取代旧的 wordlist_df
#     global_freq_dict = data.get("global_freq_dict", {})
#
#     if global_freq_dict and standard_wordlists:
#         # 统一转为小写集合，用于计算覆盖率
#         text_lemmas = {str(k).lower() for k in global_freq_dict.keys()}
#
#         st.markdown("### 📈 Vocabulary coverage statistics")
#         stats_cols = st.columns(4)
#         for idx, (level, wl_df) in enumerate(sorted(standard_wordlists.items())):
#             if idx >= 4: break
#             wordlist_lemmas = set(wl_df['lemma'].str.lower())
#             intersection = text_lemmas & wordlist_lemmas
#             coverage = (len(intersection) / len(wordlist_lemmas) * 100
#                         if wordlist_lemmas else 0)
#             with stats_cols[idx]:
#                 st.metric(label=f"COCA {(level - 1) * 5000 + 1}-{level * 5000}",
#                           value=f"{len(intersection)} words",
#                           delta=f"{coverage:.1f}% coverage")
#
#     col1, col2 = st.columns([1, 1])
#     with col1:
#         if st.button("📊 Show dependency relation types"):
#             if not data["dep_df"].empty:
#                 counts = data["dep_df"]["deprel"].value_counts()
#                 fig = px.bar(counts, x=counts.index, y=counts.values,
#                              title="Dependency relation types")
#                 st.plotly_chart(fig, use_container_width=True)
#
#     with col2:
#         if st.button("📋 Show word frequency table"):
#             if global_freq_dict:
#                 # ── ⚡ 适配修改 2：用预计算的字典直接生成精简的词频展示表 ──
#                 # 将内存字典直接转为 DataFrame，速度提升 100 倍
#                 display_df = pd.DataFrame(list(global_freq_dict.items()), columns=['lemma', 'frequency'])
#
#                 # 补充词表分级字段（如果需要结合标准词表展示它是 COCA 几）
#                 display_df['wordlist'] = 'Unknown'
#                 for level, wl_df in standard_wordlists.items():
#                     wl_set = set(wl_df['lemma'].str.lower())
#                     # 匹配属于该级别词表的单词
#                     mask = display_df['lemma'].str.lower().isin(wl_set)
#                     display_df.loc[mask, 'wordlist'] = f'COCA_{level}'
#
#
#                 def get_wordlist_order(wl):
#                     if 'COCA' in str(wl):
#                         try:
#                             return int(str(wl).split('_')[1])
#                         except:
#                             pass
#                     return 999999
#
#
#                 # 按照词表等级升序，同等级内按频次降序排列
#                 display_df['_sort_key'] = display_df['wordlist'].apply(get_wordlist_order)
#                 display_df = display_df.sort_values(['_sort_key', 'frequency'], ascending=[True, False])
#                 display_df = display_df.drop('_sort_key', axis=1)
#
#                 # 完美渲染
#                 st.dataframe(display_df[['lemma', 'frequency', 'wordlist']], use_container_width=True,
#                              hide_index=True)
# with tab3:
#     st.title("🌌 Vocabulary universe")
#
#     counter_for_stats  = (progress["global_counter"]
#                           if cumulative_mode else cumulative_counter)
#     #standard_wordlists = load_standard_wordlists()
#     #  改为直接从 Session State 获取，哪怕 rerun 1万次，这里也只是普通的字典字典引用
#     standard_wordlists = st.session_state.get("standard_wordlists", {})
#     wordlist_df        = data["wordlist"]
#
#     if not wordlist_df.empty and standard_wordlists:
#         text_lemmas = set()
#         if 'lemma' in wordlist_df.columns:
#             text_lemmas = set(wordlist_df['lemma'].str.lower())
#         st.markdown("### 📈 Vocabulary coverage statistics")
#         stats_cols = st.columns(4)
#         for idx, (level, wl_df) in enumerate(sorted(standard_wordlists.items())):
#             if idx >= 4: break
#             wordlist_lemmas = set(wl_df['lemma'].str.lower())
#             intersection   = text_lemmas & wordlist_lemmas
#             coverage       = (len(intersection) / len(wordlist_lemmas) * 100
#                               if wordlist_lemmas else 0)
#             with stats_cols[idx]:
#                 st.metric(label=f"COCA {(level-1)*5000+1}-{level*5000}",
#                           value=f"{len(intersection)} words",
#                           delta=f"{coverage:.1f}% coverage")
#
#     col1, col2 = st.columns([1, 1])
#     with col1:
#         if st.button("📊 Show dependency relation types"):
#             if not data["dep_df"].empty:
#                 counts = data["dep_df"]["deprel"].value_counts()
#                 fig    = px.bar(counts, x=counts.index, y=counts.values,
#                                 title="Dependency relation types")
#                 st.plotly_chart(fig, use_container_width=True)
#     with col2:
#         if st.button("📋 Show word frequency table"):
#             if not data["wordlist"].empty:
#                 display_df = data["wordlist"].copy()
#                 if 'wordlist' not in display_df.columns:
#                     display_df['wordlist'] = 'Unknown'
#                 def get_wordlist_order(wl):
#                     if 'COCA' in str(wl):
#                         try: return int(str(wl).split('_')[1])
#                         except: pass
#                     return 999999
#                 display_df['_sort_key'] = display_df['wordlist'].apply(get_wordlist_order)
#                 display_df = display_df.sort_values(
#                     ['_sort_key', 'frequency'], ascending=[True, False])
#                 display_df = display_df.drop('_sort_key', axis=1)
#                 st.dataframe(display_df[['lemma', 'frequency', 'wordlist']])

    # ── 行为数据面板 ──
    st.markdown("---")
    st.markdown("### 📊 Reading behavior data")

    records = query_records(username)

    if not records:
        st.info("No behavior log found. Behavior data will appear here after you read sentences.")
    else:
        st.success(f"Total records: {len(records)}")

        # ── 句级别数据（dwell_ms = dwell_seconds * 1000）──
        dwell_data = [{
            "sentence_idx": r.get("sentence_idx", ""),
            "sentence_id":  r.get("sentence_id", ""),
            "word_count":   r.get("word_count", ""),
            "dwell_ms":     round(r.get("dwell_seconds", 0) * 1000),   # [Fix-C] 统一毫秒
            "mdd":          r.get("mdd"),
            "max_dd":       r.get("max_dd"),
            "trigger":      r.get("trigger", ""),
            "clicks":       len(r.get("click_log", [])),
        } for r in records]
        dwell_df = dwell_data  # list of dict, st.dataframe accepts directly

        # ── 聚合统计 ──
        word_stats:   dict = {}
        deprel_stats: dict = {}
        pair_stats:   dict = {}

        for rec in records:
            for ev in rec.get("click_log", []):
                word     = ev.get("word") or ev.get("lemma") or "?"
                dwell_ms = ev.get("dwell_ms", 0) or 0

                if word not in word_stats:
                    word_stats[word] = {"clicks": 0, "total_dwell_ms": 0}
                word_stats[word]["clicks"]         += 1
                word_stats[word]["total_dwell_ms"] += dwell_ms

                for dep in ev.get("deps", []):
                    rel = dep.get("deprel") or "?"
                    if rel not in deprel_stats:
                        deprel_stats[rel] = {"clicks": 0, "total_dwell_ms": 0}
                    deprel_stats[rel]["clicks"]         += 1
                    deprel_stats[rel]["total_dwell_ms"] += dwell_ms

                    # [Fix-D] pair 字段直接读 dep["pair"]，格式已统一
                    pair_key = dep.get("pair") or f"{word} → {dep.get('head_lemma','?')} ({dep.get('deprel','?')})"
                    if pair_key not in pair_stats:
                        pair_stats[pair_key] = {
                            "word":           word,
                            "head_lemma":     dep.get("head_lemma", "?"),
                            "deprel":         dep.get("deprel", "?"),
                            "clicks":         0,
                            "total_dwell_ms": 0,
                        }
                    pair_stats[pair_key]["clicks"]         += 1
                    pair_stats[pair_key]["total_dwell_ms"] += dwell_ms

        # ── 构建 DataFrame ──
        # [Fix-C] 列名全部统一为 _ms，不再做 /1000
        word_df = sorted([
            {"word": w, "clicks": s["clicks"],
             "avg_dwell_ms": round(s["total_dwell_ms"] / s["clicks"]),
             "total_dwell_ms": round(s["total_dwell_ms"])}
            for w, s in word_stats.items()
        ], key=lambda r: -r["clicks"]) if word_stats else []

        deprel_df = sorted([
            {"deprel": rel, "label": label_deprel(rel), "clicks": s["clicks"],
             "avg_dwell_ms": round(s["total_dwell_ms"] / s["clicks"]),
             "total_dwell_ms": round(s["total_dwell_ms"])}
            for rel, s in deprel_stats.items()
        ], key=lambda r: -r["clicks"]) if deprel_stats else []

        pair_df = sorted([
            {"pair": k, "word": v["word"], "head_lemma": v["head_lemma"],
             "deprel": v["deprel"], "clicks": v["clicks"],
             "avg_dwell_ms": round(v["total_dwell_ms"] / v["clicks"]),
             "total_dwell_ms": round(v["total_dwell_ms"])}
            for k, v in pair_stats.items()
        ], key=lambda r: -r["clicks"]) if pair_stats else []

        # ── 指标看板 ──
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Records",              len(records))
        _dwells  = [r["dwell_ms"] for r in dwell_df if r.get("dwell_ms") is not None]
        _clicks  = [r["clicks"]   for r in dwell_df if r.get("clicks")   is not None]
        _mdds    = [r["mdd"]      for r in dwell_df if r.get("mdd")      is not None]
        avg_dwell = sum(_dwells) / len(_dwells) if len(_dwells) > 0 else 0
        m2.metric("Avg dwell (ms)", f"{avg_dwell:.0f}" if _dwells else "—")
        #m2.metric("Avg dwell (ms)",   f"{sum(_dwells)/len(_dwells):.0f}" if _dwells else "—")
        m3.metric("Total clicks",     sum(_clicks))
        m4.metric("Unique words clicked", len(word_df))
        m5.metric("Avg MDD",          f"{sum(_mdds)/len(_mdds):.2f}" if _mdds else "—")

        # ── 五个子标签 ──
        btab1, btab2, btab3, btab4, btab5 = st.tabs([
            "⏱ Dwell time", "🔤 Words clicked",
            "🔗 Dep. relations", "🔗🔗 Dep. pairs", "📋 All records",
        ])

        with btab1:
            st.markdown("**Dwell time and MDD per sentence**")
            plot_df = [r for r in dwell_df if r.get("mdd") is not None and r.get("dwell_ms") is not None]
            if plot_df:
                fig = px.scatter(
                    plot_df, x="mdd", y="dwell_ms",
                    size="word_count", color="clicks",
                    color_continuous_scale="Purples",
                    hover_data=["sentence_idx", "word_count", "max_dd", "trigger"],
                    labels={"mdd":      "Mean dependency distance",
                            "dwell_ms": "Dwell time (ms)",
                            "clicks":   "Clicks"},
                )
                fig.update_layout(margin=dict(l=0, r=0, t=24, b=0), height=340)
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("**Dwell time over sentences (chronological)**")
            if dwell_df:
                fig2 = go.Figure()
                _x_idx = list(range(len(dwell_df)))
                fig2.add_trace(go.Scatter(
                    x=_x_idx, y=[r.get("dwell_ms") for r in dwell_df],
                    mode="lines+markers", name="Dwell time (ms)",
                    line=dict(color="#7F77DD", width=1.5), marker=dict(size=4),
                ))
                fig2.add_trace(go.Scatter(
                    x=_x_idx, y=[r.get("mdd") for r in dwell_df],
                    mode="lines", name="MDD",
                    line=dict(color="#1D9E75", width=1.5, dash="dot"),
                    yaxis="y2",
                ))
                fig2.update_layout(
                    height=260, margin=dict(l=0, r=0, t=8, b=0),
                    yaxis=dict(title="Dwell time (ms)"),
                    yaxis2=dict(title="MDD", overlaying="y",
                                side="right", showgrid=False),
                    legend=dict(orientation="h", y=1.08),
                )
                st.plotly_chart(fig2, use_container_width=True)

        with btab2:
            if not word_df:
                st.info("No word clicks recorded yet.")
            else:
                st.markdown(f"**{len(word_df)} unique words clicked**")
                fig = px.bar(
                    word_df[:30], x="word", y="clicks",
                    color="avg_dwell_ms", color_continuous_scale="Purples",
                    hover_data=["avg_dwell_ms", "total_dwell_ms"],
                    labels={"word": "Word", "clicks": "Click count",
                            "avg_dwell_ms": "Avg dwell (ms)"},
                )
                fig.update_layout(height=300, margin=dict(l=0, r=0, t=8, b=0))
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("**Full table**")
                st.dataframe(
                    word_df,
                    column_config={
                        "word":           st.column_config.TextColumn("Word"),
                        "clicks":         st.column_config.NumberColumn("Clicks", format="%d"),
                        "avg_dwell_ms":   st.column_config.NumberColumn("Avg dwell (ms)", format="%d"),
                        "total_dwell_ms": st.column_config.NumberColumn("Total dwell (ms)", format="%d"),
                    },
                    use_container_width=True, hide_index=True,
                )

        with btab3:
            if not deprel_df:
                st.info("No dependency relation clicks recorded yet.")
            else:
                st.markdown(f"**{len(deprel_df)} dependency relation types triggered**")
                fig = px.bar(
                    deprel_df[:25], x="deprel", y="clicks",
                    color="avg_dwell_ms", color_continuous_scale="Teal",
                    hover_data=["label", "avg_dwell_ms", "total_dwell_ms"],
                    labels={"deprel": "Relation", "clicks": "Click count",
                            "avg_dwell_ms": "Avg dwell (ms)"},
                )
                fig.update_layout(height=300, margin=dict(l=0, r=0, t=8, b=0))
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("**Full table**")
                st.dataframe(
                    deprel_df,
                    column_config={
                        "deprel":         st.column_config.TextColumn("Relation"),
                        "label":          st.column_config.TextColumn("Description"),
                        "clicks":         st.column_config.NumberColumn("Clicks", format="%d"),
                        "avg_dwell_ms":   st.column_config.NumberColumn("Avg dwell (ms)", format="%d"),
                        "total_dwell_ms": st.column_config.NumberColumn("Total dwell (ms)", format="%d"),
                    },
                    use_container_width=True, hide_index=True,
                )

        with btab4:
            if not pair_df:
                st.info("No dependency pair clicks recorded yet.")
            else:
                st.markdown(f"**{len(pair_df)} unique dependency pairs triggered**")
                fig = px.bar(
                    pair_df[:25], x="pair", y="clicks",
                    color="avg_dwell_ms", color_continuous_scale="Blues",
                    hover_data=["word", "head_lemma", "deprel", "avg_dwell_ms"],
                    labels={"pair": "Pair", "clicks": "Click count",
                            "avg_dwell_ms": "Avg dwell (ms)"},
                )
                fig.update_layout(height=300, margin=dict(l=0, r=0, t=8, b=0),
                                  xaxis_tickangle=-35)
                st.plotly_chart(fig, use_container_width=True)
                st.markdown("**Full table**")
                st.dataframe(
                    pair_df,
                    column_config={
                        "pair":           st.column_config.TextColumn("Pair (word → head)"),
                        "word":           st.column_config.TextColumn("Word"),
                        "head_lemma":     st.column_config.TextColumn("Head"),
                        "deprel":         st.column_config.TextColumn("Relation"),
                        "clicks":         st.column_config.NumberColumn("Clicks", format="%d"),
                        "avg_dwell_ms":   st.column_config.NumberColumn("Avg dwell (ms)", format="%d"),
                        "total_dwell_ms": st.column_config.NumberColumn("Total dwell (ms)", format="%d"),
                    },
                    use_container_width=True, hide_index=True,
                )

        with btab5:
            summary_rows = []
            for rec in records:
                cl = rec.get("click_log", [])
                summary_rows.append({
                    "timestamp":    rec.get("timestamp", ""),
                    "sentence_idx": rec.get("sentence_idx", ""),
                    "word_count":   rec.get("word_count", ""),
                    "dwell_ms":     round(rec.get("dwell_seconds", 0) * 1000),
                    "mdd":          rec.get("mdd"),
                    "max_dd":       rec.get("max_dd"),
                    "trigger":      rec.get("trigger", ""),
                    "clicks":       len(cl),
                    "Clicked Word": ", ".join(sorted(set(
                        ev.get("word", "") or ev.get("lemma", "")
                        for ev in cl if ev.get("word") or ev.get("lemma")
                    ))),
                    "Dependency Relation": ", ".join(sorted(set(
                        dep.get("deprel", "")
                        for ev in cl
                        for dep in ev.get("deps", [])
                        if dep.get("deprel")
                    ))),
                    "Dependency Pair": ", ".join(sorted(set(
                        dep.get("pair", "")
                        for ev in cl
                        for dep in ev.get("deps", [])
                        if dep.get("pair")
                    ))),
                })
            st.dataframe(
                summary_rows,
                column_config={
                    "timestamp":           st.column_config.TextColumn("Timestamp"),
                    "sentence_idx":        st.column_config.NumberColumn("Sent.", format="%d"),
                    "word_count":          st.column_config.NumberColumn("Words", format="%d"),
                    "dwell_ms":            st.column_config.NumberColumn("Dwell (ms)", format="%d"),
                    "mdd":                 st.column_config.NumberColumn("MDD", format="%.2f"),
                    "max_dd":              st.column_config.NumberColumn("MaxDD", format="%d"),
                    "trigger":             st.column_config.TextColumn("Trigger"),
                    "clicks":              st.column_config.NumberColumn("Clicks", format="%d"),
                    "Clicked Word":        st.column_config.TextColumn("Words clicked"),
                    "Dependency Relation": st.column_config.TextColumn("Deprels triggered"),
                    "Dependency Pair":     st.column_config.TextColumn("Dep pairs triggered"),
                },
                use_container_width=True, hide_index=True,
            )

        # ── 下载 ──
        st.markdown("---")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            # 1. 先獲取該用戶對應的完整文件路徑
            user_log_file = get_behavior_log_path(username)

            # 2. 安全讀取數據，若文件不存在則給予空數據防崩潰
            if user_log_file.is_file():
                log_data = user_log_file.read_bytes()
            else:
                log_data = b""  # 或者 b"[]"

            # 3. 渲染下載按鈕
            st.download_button(
                label="⬇️ Download full JSONL",
                data=log_data,
                file_name=f"reading_behavior_{username}.jsonl",
                mime="application/jsonl",
            )
            # st.download_button(
            #     label = "⬇ Download full JSONL",
            #     data = LOGS_DIR.read_bytes(),
            #     file_name = f"reading_behavior_{username}.jsonl",
            #     mime = "application/jsonl",
            #)
        # with dl_col2:
        #     csv_buf = dwell_df.to_csv(index=False).encode()
        #     st.download_button(
        #         label="⬇ Download summary CSV",
        #         data=csv_buf,
        #         file_name=f"reading_summary_{username}.csv",
        #         mime="text/csv",
        #     )
        with dl_col2:
            # 1. 建立內存緩衝區
            csv_output = io.StringIO()

            # 2. 定義 CSV 的表頭欄位（必須和 dwell_df 裡的字典鍵名完全一致）
            fieldnames = ["sentence_idx", "sentence_id", "word_count", "dwell_ms", "mdd", "max_dd", "trigger", "clicks"]

            writer = csv.DictWriter(csv_output, fieldnames=fieldnames)
            writer.writeheader()  # 寫入表頭

            # 3. 安全寫入原生 list 數據
            if dwell_df and isinstance(dwell_df, list):
                writer.writerows(dwell_df)

            csv_buf = csv_output.getvalue().encode('utf-8')
            csv_output.close()

            # 4. 渲染下載按鈕
            st.download_button(
                label="⬇️ Download summary CSV",
                data=csv_buf,
                file_name=f"reading_summary_{username}.csv",
                mime="text/csv",
            )