# 正式部署版（基于 English_Reader_033，在 Streamlit Cloud 运行）
# streamlit run "D:\软件\四级词汇比例-频率-缺失率\003-English_Reader_033.py"
# 相对 033 的改动共 5 处，其余代码完全不变：
#   [改动1] import 新增 auth / data_loader / book_registry 三个本地模块
#   [改动2] 路径配置块替换为 GitHub 动态加载（data_loader）
#   [改动3] 用户系统替换为远程 FastAPI 认证（auth）
#   [改动4] 侧边栏书籍选择改为从 book_registry 动态生成，支持免费/付费分层
#   [改动5] 免费体验策略：注册后14天全功能免费，到期后每天3句

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
#from pathlib import Path
from collections import Counter
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import re
import time
import json
#from nltk.stem import WordNetLemmatizer
#from nltk.corpus import wordnet
#import nltk
import requests
from io import BytesIO
import html
import hashlib
import secrets
#import asyncio
import edge_tts
import tempfile
from pathlib import Path
# 🔍 补上这行：定义服务器上存放词汇表（COCA等）的绝对路径
#WORDLISTS_DIR = Path("/opt/prism/app/wordlists")
# ==================== 路径配置块 ====================
BASE_DIR = Path("/opt/prism/logs")
BASE_DIR.mkdir(parents=True, exist_ok=True)

WORDLISTS_DIR = Path("/opt/prism/app/wordlists")
# 如果新版词汇宇宙或者 load_wordlist_data 还会用到 SINGLE/COMBINED 分析结果，也应一并统一到自托管路径：
SINGLE_DIR = Path("/opt/prism/app/vocabulary/single")
COMBINED_DIR = Path("/opt/prism/app/vocabulary/combined")



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
from data_loader import load_book_from_server
from book_registry import BOOK_REGISTRY


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
BASE_DIR = Path("/opt/prism/logs")
BASE_DIR.mkdir(parents=True, exist_ok=True)
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


@st.cache_data
def load_standard_wordlists():
    wordlists = {}
    if not WORDLISTS_DIR.exists():
        return wordlists
    file_names = ["COCA_20000_part1.txt", "COCA_20000_part2.txt",
                  "COCA_20000_part3.txt", "COCA_20000_part4.txt"]
    for i, file_name in enumerate(file_names, 1):
        wordlist_path = WORDLISTS_DIR / file_name
        if wordlist_path.exists():
            with open(wordlist_path, 'r', encoding='utf-8') as f:
                lemmas = [line.strip().lower() for line in f if line.strip()]
            df = pd.DataFrame({'lemma': lemmas, 'order': range(len(lemmas))})
            wordlists[i] = df
    return wordlists
# ─── ✨ 【新增改动点：全局一次性加载词汇表】 ───
if "standard_wordlists" not in st.session_state:
    # 只有当全新的 Session 建立、第一次跑这个脚本时，才会触发这一块
    with st.spinner("Initializing vocabulary database..."):
        try:
            # 这里调用的是你本来就定义好的本地加载函数
            st.session_state["standard_wordlists"] = load_standard_wordlists()
        except Exception as e:
            # 增加安全兜底：防止路径配置错误或文件缺失直接导致整个 App 白屏挂掉
            st.error(f"⚠️ Vocabulary database loading failed: {e}")
            st.session_state["standard_wordlists"] = {}
# ────────────────────────────────────────────────

def load_wordlist_data(book_stem, dp_folder):
    # single_path   = SINGLE_DIR   / f"{book_stem}_vocabulary_analysis.csv"
    # combined_path = COMBINED_DIR / f"{book_stem}_vocabulary_analysis.csv"
    # 增加路径存在性校验，防止单机路径未定义引发 NameError
    single_path = SINGLE_DIR / f"{book_stem}_vocabulary_analysis.csv" if 'SINGLE_DIR' in globals() else None
    combined_path = COMBINED_DIR / f"{book_stem}_vocabulary_analysis.csv" if 'COMBINED_DIR' in globals() else None
    if single_path and single_path.exists():
        wordlist_df = pd.read_csv(single_path)
    elif combined_path.exists():
        wordlist_df = pd.read_csv(combined_path)
    else:
        freq_path = dp_folder / "lemma_frequency.csv"
        if freq_path.exists():
            wordlist_df = pd.read_csv(freq_path)
            if 'wordlist' not in wordlist_df.columns:
                #standard_wordlists = load_standard_wordlists()
                standard_wordlists = st.session_state.get("standard_wordlists", {})
                wordlist_mapping = []
                for _, row in wordlist_df.iterrows():
                    lemma  = str(row.get('lemma', '')).lower()
                    source = '未知'
                    for level, wl_df in standard_wordlists.items():
                        if lemma in wl_df['lemma'].values:
                            source = f'COCA_{level * 5000}'
                            break
                    wordlist_mapping.append(source)
                wordlist_df['wordlist'] = wordlist_mapping
        else:
            return pd.DataFrame()
    return wordlist_df

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


def get_word_sentences(lemma, sentences_df, all_sentence_lemmas):
    matching = []
    for idx, sent_lemmas in enumerate(all_sentence_lemmas):
        if lemma in sent_lemmas:
            matching.append({
                "sentence_id": sentences_df.iloc[idx]["sentence_id"],
                "text":        sentences_df.iloc[idx].get("tokenized_sentence", ""),
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
def get_word_dependencies(clicked_word: str, current_sentence_id: int, dep_df: pd.DataFrame):
    """
    直接通过预计算好的 Lemma 列进行 O(1) 匹配，不再实时计算还原
    """
    # if dep_df is empty or dep_df is None:
    #     return []
    # ✅ 正确的 DataFrame 判空与守卫
    if dep_df is None or (isinstance(dep_df, pd.DataFrame) and dep_df.empty):
        st.warning("⚠️ No dependency tree data available for this book.")

    # 1. 统一转换用户点击的词为小写（作为基础匹配依据）
    click_lemma = clicked_word.strip().lower()

    # 2. 筛选当前句子的依存子集
    sub_df = dep_df[dep_df['sentence_id'] == current_sentence_id]
    if sub_df.empty:
        return []

    # 3. 直接利用预计算好的 dependent_lemma 和 head_lemma 查找关联
    # 关联条件：点击的词是“依赖词”或“核心词”
    matched = sub_df[
        (sub_df['dependent_lemma'] == click_lemma) |
        (sub_df['head_lemma'] == click_lemma)
        ]

    dependencies = []
    for _, row in matched.iterrows():
        dependencies.append({
            'dep_word': row['dependent_text'],
            'head_word': row['head_text'],
            'deprel': row['deprel'],
            'dep_lemma': row['dependent_lemma'],  # 直接使用预计算值
            'head_lemma': row['head_lemma']  # 直接使用预计算值
        })

    return dependencies


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

def generate_dep_arc_html(dep_df, sentence_id) -> str:
    sent = dep_df[dep_df["sentence_id"] == sentence_id].copy()
    if sent.empty:
        return ""
    sent      = sent.sort_values("dependent_id")
    word_dict = {}
    for _, row in sent.iterrows():
        dep_id = int(row["dependent_id"])
        if dep_id not in word_dict:
            word_dict[dep_id] = {
                "id": dep_id, "text": str(row["dependent_text"]),
                "upos": str(row.get("upos", "?"))
            }
        head_id = int(row["head_id"])
        if head_id > 0 and head_id not in word_dict:
            word_dict[head_id] = {"id": head_id, "text": str(row["head_text"]), "upos": "?"}
    sorted_words = sorted(word_dict.values(), key=lambda x: x["id"])
    words_js = [f'{{id:{w["id"]},text:"{w["text"]}",pos:"{w["upos"]}"}}' for w in sorted_words]
    deps_js  = [
        f'{{dep:{int(row["dependent_id"])},head:{int(row["head_id"])},rel:"{row["deprel"]}"}}'
        for _, row in sent.iterrows()
    ]
    return (arc_html_template
            .replace("__WORDS__", "[" + ",".join(words_js) + "]")
            .replace("__DEPS__",  "[" + ",".join(deps_js)  + "]"))


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
def compute_dep_distances(sent_deps_df: pd.DataFrame) -> dict:
    if sent_deps_df.empty:
        return {"dep_pairs": [], "mdd": None, "max_dd": None}
    pairs     = []
    distances = []
    for _, row in sent_deps_df.iterrows():
        try:
            dep_id  = int(row["dependent_id"])
            head_id = int(row["head_id"])
        except (ValueError, TypeError):
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
    return BASE_DIR / f"reading_behavior_{username}.jsonl"
# ===================================================================
# 行为数据持久化
# ===================================================================

# ✨ 新增：支持 Numpy/Pandas 各种数据类型的智能 JSON 编码器
class NpPandasJsonEncoder(json.JSONEncoder):
    def default(self, obj):
        # 1. 处理 Numpy 整数 (int64, int32等)
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        # 2. 处理 Numpy 浮点数 (float64, float32等)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        # 3. 处理 Numpy 数组
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        # 4. 处理 Pandas 的可空 Int64/Float64 以及 NAType
        elif pd.isna(obj): # 自动兼容 pd.NA 和 np.nan，转为 JSON 的 null
            return None
        try:
            # 5. 兜底处理：部分特殊的 Pandas 标量类型
            if hasattr(obj, 'item'):
                return obj.item()
        except Exception:
            pass
        return super().default(obj)

# def append_behavior_record(username: str, record: dict):
#     path = get_behavior_log_path(username)
#     try:
#         with open(path, "a", encoding="utf-8") as f:
#             f.write(json.dumps(record, ensure_ascii=False) + "\n")
#     except Exception:
#         pass
def append_behavior_record(username: str, record: dict):
    path = get_behavior_log_path(username)
    try:
        with open(path, "a", encoding="utf-8") as f:
            # ✨ 核心改动：挂载智能编码器 cls=NpPandasJsonEncoder
            serialized_str = json.dumps(record, ensure_ascii=False, cls=NpPandasJsonEncoder)
            f.write(serialized_str + "\n")
    except Exception as e:
        # 🛡️ 极其重要的防御性日志：如果在自托管控制台里跑，至少能看到为什么失败
        import logging
        logging.error(f"Failed to save behavior record for {username}: {e}")
        # 如果你想在 Streamlit 页面隐蔽处打印，也可以放开下面这行（可选）：
        # st.sidebar.error(f"Log Error: {e}")


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
        cleaned = re.sub(r"[^\w''\-]", "", word.lower())
        cleaned = cleaned.strip("''-")
        is_word = bool(re.search(r'[a-zA-Z]', cleaned)) if cleaned else False
        lemma = None
        freq  = 0
        deps_info = []

        if is_word:
            for_lemma = re.sub(r"[''`\-]", "", cleaned)
            if for_lemma:
                lemma = cached_lemmatize(for_lemma)
                running_counter[lemma] += 1
                freq = running_counter[lemma]

            # [Fix-A] embed dep 信息：dep_map_by_position 的 key = dependent_id - 1
            # 这里用 split_idx（0-based 词序）作为 key，与 dependent_id-1 对应
            if dep_map_by_position is not None:
                for related_idx, deprel, related_lemma in dep_map_by_position.get(split_idx, []):
                    deps_info.append({
                        "head_lemma": str(related_lemma),
                        "deprel":     str(deprel),
                        # [Fix-D] pair 格式统一为 "word → head_lemma (deprel)"
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
# [Fix-A] 修复后的交互式句子 HTML 生成函数（接口不变，内部用 token.deps_info）
# ===================================================================
def generate_interactive_sentence_html(words, dep_map_by_position, dep_roles_by_position,
                                       sentence_id, core_lemmas, modifier_lemmas,
                                       book_name, display_sentence, simplify_mode=None):

    def should_show_word(word_idx):
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

    html_parts     = []
    word_data_json = []

    for idx, word_data in enumerate(words):
        word  = word_data['display']
        lemma = word_data.get('lemma')
        freq  = word_data.get('freq', 0)

        if lemma and not should_show_word(idx):
            continue

        if lemma:
            color    = get_color(freq)
            size_str, font = get_font_style_by_frequency(freq)
            size     = int(size_str.replace('px', ''))
            styles   = [f"color:{color}", f"font-size:{size}px",
                        f"font-family:{font}", "cursor:pointer"]
            if lemma in core_lemmas:     styles.append("font-weight:bold")
            if lemma in modifier_lemmas: styles.append("font-style:italic")
            style_str = "; ".join(styles)

            # 用 token 里预存的 deps_info 构建 JS 数据（保持 iframe 高亮功能）
            # dep_data = []
            # if idx in dep_map_by_position:
            #     for related_idx, deprel, related_lemma in dep_map_by_position[idx]:
            #         dep_data.append({
            #             'position': related_idx,
            #             'lemma':    related_lemma,
            #             'deprel':   deprel,
            #         })

            #  改为直接从 word_data 中读取预存的对齐数据：
            dep_data = []
            if 'deps_info' in word_data and word_data['deps_info']:
                for dep_item in word_data['deps_info']:
                    dep_data.append({
                        'position': dep_item.get('related_idx'),  # 对应 JS 中的 dep.position
                        'lemma': dep_item.get('related_lemma'),
                        'deprel': dep_item.get('deprel'),
                    })
            word_data_json.append({
                'idx': idx, 'lemma': lemma, 'word': word, 'deps': dep_data
            })
            html_parts.append(
                f'<span class="word" data-idx="{idx}" '
                f'data-lemma="{html.escape(lemma)}" '
                f'style="{style_str}">{html.escape(word)}</span> '
            )
        # else:
        #     html_parts.append(
        #         f'<span style="color:#555555; font-size:15px; '
        #         f'font-family:Merriweather">{html.escape(word)}</span> '
        #     )
        else:
            # 将字号调整到 24px - 26px 左右，与主体视觉对齐
            html_parts.append(
                f'<span style="color:#666666; font-size:26px; '
                f'font-family:Merriweather, serif">{html.escape(word)}</span> '
            )

    sentence_html = ''.join(html_parts)

    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            margin: 0; padding: 20px;
            font-family: Arial, sans-serif; background: #F5E6C8;
        }}
        .sentence-container {{
            font-size: 28px; line-height: 2.5; padding: 20px;
            background: #F5E6C8; border-radius: 10px;
            cursor: default; user-select: none;
        }}
        .word {{
            transition: background-color 0.2s;
            padding: 2px 4px; border-radius: 3px;
        }}
        .word:hover {{ background-color: #f0f0f0; }}
        .dep-relation {{
            margin-top: 15px; padding: 15px; background: #e3f2fd;
            border-radius: 8px; font-size: 16px;
            border-left: 4px solid #2196F3; animation: fadeIn 0.3s;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-10px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}
        .relation-title {{ font-weight: bold; margin-bottom: 8px; color: #1976D2; }}
        .relation-item  {{ margin: 5px 0; padding: 5px; background: white; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="sentence-container" id="sentenceContainer">
        {sentence_html}
    </div>
    <div id="depRelationContainer"></div>

    <script>
        const wordData     = {json.dumps(word_data_json)};
        const deprelLabels = {json.dumps(DEPREL_LABELS)};

        const idxToElement = new Map();
        wordData.forEach(d => {{
            const el = document.querySelector(`.word[data-idx="${{d.idx}}"]`);
            if (el) idxToElement.set(d.idx, el);
        }});

        document.querySelectorAll('.word').forEach(el => {{
            el.addEventListener('click', function(e) {{
                e.stopPropagation();
                handleClick(this);
            }});
        }});

        function handleClick(element) {{
            clearHighlights();
            const idx  = parseInt(element.dataset.idx);
            const data = wordData.find(d => d.idx === idx);
            if (!data) return;

            element.style.outline = '3px solid #39FF14';
            data.deps.forEach(dep => {{
                const relEl = idxToElement.get(dep.position);
                if (relEl) relEl.style.outline = '3px solid #39FF14';
            }});

            if (data.deps.length > 0) showDependencies(data);
        }}

        function showDependencies(data) {{
            const container = document.getElementById('depRelationContainer');
            container.innerHTML = '';
            const div = document.createElement('div');
            div.className = 'dep-relation';
            let h = '<div class="relation-title">Dependency relations:</div>';
            data.deps.forEach(dep => {{
                const note  = deprelLabels[dep.deprel] || dep.deprel;
                const label = (note !== dep.deprel)
                    ? note + ' (' + dep.deprel + ')' : dep.deprel;
                h += `<div class="relation-item">
                    <strong>${{data.word}}</strong>
                    ──${{label}}──&gt;
                    <strong>${{dep.lemma}}</strong>
                    </div>`;
            }});
            div.innerHTML = h;
            container.appendChild(div);
        }}

        function clearHighlights() {{
            document.querySelectorAll('.word').forEach(w => w.style.outline = '');
            document.getElementById('depRelationContainer').innerHTML = '';
        }}

        document.addEventListener('click', function(e) {{
            if (!e.target.classList.contains('word')) clearHighlights();
        }});
    </script>
</body>
</html>"""
    return full_html


# ===================================================================
# [改动4] Session 初始化 + 侧边栏
# 认证：改用 auth.py 连接远程 FastAPI
# 书籍选择：改用 book_registry.py，支持免费/付费分层
# ===================================================================

# ── 1. 全局核心 Session State 初始化（增加条件判定，防止频繁 Rerun 导致的重置死循环） ──
if "is_logged_in" not in st.session_state:
    st.session_state.is_logged_in = False

if "username" not in st.session_state:
    st.session_state.username = "guest"

# ⚡ [优化点1]：将状态重置函数包裹在条件门禁中，只有在首次进入或必要时才执行一次
if "states_initialized" not in st.session_state:
    reset_default_session_state()
    st.session_state["states_initialized"] = True

# 初始化阅读行为打点所需的专用计时与缓存字典
if "_sentence_enter_time" not in st.session_state:
    st.session_state["_sentence_enter_time"] = {}
if "_pending_behavior_save" not in st.session_state:
    st.session_state["_pending_behavior_save"] = None


# ── 2. 远程身份认证组件（调用 auth.py 渲染侧边栏） ──
# 内部成功登录后，应当自动将 st.session_state.is_logged_in 设为 True，并将账号写入 st.session_state.username
render_auth_sidebar()


# ── 3. 全局未登录权限拦截门禁 ──
if not st.session_state.is_logged_in or st.session_state.username == "guest":
    st.info("👋 Welcome! Please log in or register in the sidebar to start your smart reading journey.")
    st.stop()  # ⛔ 强行阻断下游代码渲染，保护核心内容付费墙和付费书籍资产

# ── 4. 权限通过，全局变量安全派生 ──
# 下游的所有组件（包括日志记录器、书籍展示墙）将统一且安全地调用此 username 变量
username = st.session_state.username
# if "current_user" not in st.session_state:
#     st.session_state.current_user = None
#
# reset_default_session_state()
#
# if "_sentence_enter_time"   not in st.session_state:
#     st.session_state["_sentence_enter_time"]   = {}
# if "_pending_behavior_save" not in st.session_state:
#     st.session_state["_pending_behavior_save"] = None
#
# # ── 认证（来自 auth.py，支持注册/登录/忘记密码）──
# render_auth_sidebar()
#
# if not st.session_state.current_user:
#     st.info("Please log in or register in the sidebar to start reading.")
#     st.stop()
#
# username = st.session_state.current_user

# ── 订阅状态 + 付款入口 ──
render_subscription_sidebar()
#sub = check_subscription()

# ══════════════════════════════════════════════════════════════
# 优化后：仅在初次登录或状态不存在时请求一次，之后点击按钮直接读内存
# ══════════════════════════════════════════════════════════════
# 1. 检查名为 "sub" 的缓存格子是否存在（必须加引号，代表字符串键名）
if "sub" not in st.session_state:
    # 2. 如果不存在，调用函数拿结果，并存入缓存（点语法 st.session_state.sub 是完全正确的）
    st.session_state.sub = check_subscription()

# 3. 从缓存中取出值，赋给本地变量 sub 供后续代码使用
sub = st.session_state.sub


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
with st.spinner(f"Loading {book_choice}…"):
    data = load_book_from_server(book_name, book_info["repo"])

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

    sentences_df        = data["sentences"]
    all_sentence_lemmas = data["all_sentence_lemmas"]
    global_freq_dict    = data["global_freq_dict"]
    total_sentences     = len(sentences_df)

    max_view    = current_sentence if current_sentence < total_sentences else total_sentences - 1
    view_key    = f"view_sentence_{book_name}"
    slider_key  = f"slider_{book_name}"
    pending_key = f"_pending_{book_name}"

    if view_key not in st.session_state:
        st.session_state[view_key] = 0

    if pending_key in st.session_state:
        target = st.session_state.pop(pending_key)
        target = max(0, min(target, max_view))
        st.session_state[view_key]   = target
        st.session_state[slider_key] = target
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
    dep_index   = data["dep_index"]
    core_lemmas     = set()
    modifier_lemmas = set()
    dep_roles_by_position = {}
    dep_map_by_position   = {}

    row           = sentences_df.iloc[display_sentence]
    sentence_text = row.get("tokenized_sentence", "")
    sentence_id   = row["sentence_id"]
    sent_deps_df  = dep_index.get(sentence_id, pd.DataFrame())

    sent_deps_df = dep_index.get(sentence_id, [])

    # 兼容两种结构的判空
    is_valid_deps = false
    if isinstance(sent_deps_df, pd.DataFrame):
        is_valid_deps = not sent_deps_df.empty
    else:
        is_valid_deps = len(sent_deps_df) > 0

    if is_valid_deps:
        core_rels = {"nsubj", "nsubj:pass", "obj", "iobj", "csubj", "csubj:pass", "ccomp", "xcomp", "root", "ROOT"}
        modifier_rels = {"amod", "advmod", "obl", "nmod", "appos", "acl", "acl:relcl"}

        # 动态选择迭代器
        iterator = sent_deps_df.iterrows() if isinstance(sent_deps_df, pd.DataFrame) else enumerate(sent_deps_df)

        for _, r in iterator:

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
    dep_dist_info = compute_dep_distances(sent_deps_df)

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
    interactive_html = generate_interactive_sentence_html(
        sentence_tokens, dep_map_by_position, dep_roles_by_position,
        sentence_id, core_lemmas, modifier_lemmas,
        book_name, display_sentence, st.session_state.get('simplify_mode'))
    components.html(interactive_html, height=400, scrolling=True)

    # ── Word click tracker ──
    st.markdown("**🖱 Click words below to record the log:**")
    valid_tokens = [(idx, t) for idx, t in enumerate(sentence_tokens) if t.get("lemma")]

    # [诊断] 显示当前句有多少个 token 有 deps_info
    tokens_with_deps = [(idx, t) for idx, t in valid_tokens if t.get("deps_info")]
    if tokens_with_deps:
        st.caption(
            f"ℹ️ {len(tokens_with_deps)} words have dependency info embedded: "
            + ", ".join(f"{t['display']}({len(t['deps_info'])})" for _, t in tokens_with_deps[:8])
        )
    else:
        st.caption("⚠️ No dependency info found for any token in this sentence. "
                   "Check that dep_map_by_position keys match split() positions.")

    if valid_tokens:
        cols_per_row = 6
        for i in range(0, len(valid_tokens), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, (idx, token) in enumerate(valid_tokens[i:i + cols_per_row]):
                with cols[j]:
                    btn_key = f"click_{book_name}_{display_sentence}_{idx}_{token['lemma']}"
                    if st.button(token["display"], key=btn_key, use_container_width=True):
                        now = time.time()
                        last_key = f"_last_click_time_{book_name}_{sentence_id}"
                        last_click_time = st.session_state.get(last_key)
                        dwell_ms = int((now - last_click_time) * 1000) if last_click_time else 0
                        st.session_state[last_key] = now

                        # [Fix-B] 直接从 token 的 deps_info 读取
                        ev = _build_click_event(token, dwell_ms=dwell_ms)
                        current_click_log.append(ev)
                        st.session_state[click_cache_key] = current_click_log

                        dep_summary = (
                            f" → deps: {', '.join(d['deprel'] for d in ev['deps'])}"
                            if ev['deps'] else " (no deps)"
                        )
                        st.success(f"Recorded: {token['display']}{dep_summary}")

    if current_click_log:
        st.caption(
            f"Recorded clicks for this sentence: {len(current_click_log)} | "
            f"Words: {', '.join(dict.fromkeys(ev.get('word','?') for ev in current_click_log))}"
        )
    else:
        st.info("No word clicks recorded yet. Click the words above to create a log entry.")

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
        interaction_df = pd.DataFrame([{
            "Clicked Word":       ", ".join(clicked_words)  if clicked_words  else "—",
            "Dependency Relation": ", ".join(clicked_rels)  if clicked_rels   else "—",
            "Dependency Pair":    ", ".join(clicked_pairs)  if clicked_pairs  else "—",
        }])
        st.dataframe(interaction_df, hide_index=True, use_container_width=True)

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
            st.dataframe(pd.DataFrame(pairs_display),
                         use_container_width=True, hide_index=True)

    # ── TTS ──

    # ── TTS 语音朗读模块 ──
    tts_col1, _ = st.columns([1, 4])
    tts_audio_key = f"tts_audio_{book_name}_{display_sentence}"

    with tts_col1:
        # 按钮加上 key，防止 Streamlit 在组件销毁重建时产生状态混乱
        if st.button("🔊 Play Audio", key=f"btn_tts_{book_name}_{display_sentence}"):
            with st.spinner("Generating audio..."):
                try:
                    # 1. 异步调用 edge-tts 生成音频
                    # 无论当前处于何种线程/事件循环，因为顶部已经 apply 了 nest_asyncio，直接 run 绝对安全
                    mp3_path = asyncio.run(do_tts(sentence_text, tts_voice))

                    # 2. ⚡ 核心安全改动：立即从物理磁盘读入内存字节流，摆脱临时文件并发控制的泥潭
                    from pathlib import Path

                    audio_bytes = Path(mp3_path).read_bytes()

                    # 3. 将字节流存入当前句子的专属 Session 状态中
                    st.session_state[tts_audio_key] = audio_bytes

                    # 4. 尝试安全地删除刚刚产生的临时物理文件，保持服务器磁盘整洁
                    try:
                        Path(mp3_path).unlink()
                    except Exception:
                        pass

                except Exception as e:
                    st.error(f"TTS generation failed: {e}")

    # ✨ 状态渲染屏障：只要当前句子的音频在缓存里，就稳稳地渲染播放器，Rerun 刷新也不会消失
    if tts_audio_key in st.session_state and st.session_state[tts_audio_key]:
        st.audio(st.session_state[tts_audio_key], format="audio/mp3")
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
        st.markdown("**💾 Add to wordbook (click words):**")
        valid_tokens_wb = [t for t in sentence_tokens if t.get('lemma')]
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
        sent_deps = data["dep_df"][data["dep_df"]["sentence_id"] == sentence_id]
        if not sent_deps.empty:
            st.subheader("Dependency relations")
            for _, r in sent_deps.iterrows():
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
            arc_html = generate_dep_arc_html(data["dep_df"], sentence_id)
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

    with ctrl_col2:
        # ✨ 【核心新增：跳读输入框】
        # 显示给用户 1-based (从 1 开始的序号)，后台自动转换对齐到 0-based 数组
        max_valid_idx = int(total_sentences)
        display_idx = display_sentence + 1

        target_sentence_1based = st.number_input(
            label="🎯 Jump to Sentence:",
            min_value=1,
            max_value=max_valid_idx,
            value=int(display_idx),
            step=1,
            label_visibility="collapsed",  # 隐藏上方的多余提示文字，保持排版精简
            key=f"jump_input_v3_{book_name}_{display_sentence}"
        )

        # 💡 联动监听：如果用户输入的页码发生了改变（代表敲击了回车或按了加减）
        target_sentence_0based = target_sentence_1based - 1
        if target_sentence_0based != display_sentence:
            leave_time = time.time()
            enter_time = st.session_state["_sentence_enter_time"].get(enter_key, leave_time)
            dwell_secs = round(leave_time - enter_time, 2)

            # ⚡ 完美融入：跳读时也生成一条对应的行为日志，并将 trigger 标记为 "jump_input"
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
                "trigger": f"jump_to_{target_sentence_1based}",  # 动态记录跳读目标，极其利于后续科研行为分析
                "click_log": current_click_log,
            }
            st.session_state["_pending_behavior_save"] = behavior_record
            st.session_state.pop(click_cache_key, None)
            st.session_state["_sentence_enter_time"].pop(enter_key, None)

            # 变更进度指针并保存刷新
            st.session_state[pending_key] = target_sentence_0based
            save_progress()
            st.rerun()

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
                    selected_lemma, sentences_df, all_sentence_lemmas)
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
                        dep_df = data.get("dep_df", pd.DataFrame())

                        # ── ⚡ 适配修改 2：直接基于新版预计算列进行全表筛选 ──
                        if not dep_df.empty:
                            # 匹配 dependent_lemma 或 head_lemma 等于当前查询词的所有依存记录
                            matched_deps = dep_df[
                                (dep_df['dependent_lemma'] == lemma_dep) |
                                (dep_df['head_lemma'] == lemma_dep)
                                ]
                        else:
                            matched_deps = pd.DataFrame()

                        if not matched_deps.empty:
                            st.subheader("Dependency relations (ordered by sentence index)")
                            current_sid = sentences_df.iloc[display_sentence]["sentence_id"]
                            shown = 0

                            # 按照句子的原始顺序升序排列显示
                            matched_deps = matched_deps.sort_values(by="sentence_id")

                            for _, row in matched_deps.iterrows():
                                if shown >= 200:
                                    break

                                sid = int(row['sentence_id'])
                                # 动态拼装可读性更高的关系文本，代替旧版未定义的 relation 字段
                                relation = f"[{row['dependent_text']}] --({row['deprel']})--> [{row['head_text']}]"

                                # 高亮当前用户正在阅读的句子
                                if sid == current_sid:
                                    st.markdown(f"**★ [{sid}]** `{relation}`")
                                else:
                                    st.text(f"[{sid}] {relation}")
                                shown += 1

                            if len(matched_deps) > 200:
                                st.info(
                                    f"{len(matched_deps)} relations in total, "
                                    f"showing the first 200.")
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
#                     selected_lemma, sentences_df, all_sentence_lemmas)
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

    # ── ⚡ 核心对齐修改 1：利用 O(1) 前缀和计算用户当前真正“见过”的词频计数器 ──
    # 彻底杜绝原本“不论读到哪，都只显示全书静态死数据”的缺陷
    if cumulative_mode:
        # 累计模式：使用用户跨书籍的全局历史累计词频
        user_seen_counter = progress.get("global_counter", Counter())
    else:
        # 单书模式：利用预计算的前缀和 + 当前句增量，瞬时(O(1))还原出用户当前的真实阅读词频进度
        if "prefix_counters" in data and current_sentence < len(data["sentence_deltas"]):
            # 到达当前句之前的所有累计词频缓存
            user_seen_counter = data["prefix_counters"][current_sentence].copy()
            # 加上当前这一句所贡献的词频
            user_seen_counter.update(data["sentence_deltas"][current_sentence])
        else:
            # 兜底逻辑
            user_seen_counter = Counter()

    # 从 Session State 获取官方的标准词汇分级表（COCA等）
    standard_wordlists = st.session_state.get("standard_wordlists", {})

    # ── 📈 动态词汇覆盖率统计 ──
    if user_seen_counter and standard_wordlists:
        # 统一转为小写集合，用于高精度集合交集计算
        text_lemmas = {str(k).lower().strip() for k in user_seen_counter.keys()}

        st.markdown("### 📈 Vocabulary coverage statistics (Current Progress)")
        stats_cols = st.columns(4)
        for idx, (level, wl_df) in enumerate(sorted(standard_wordlists.items())):
            if idx >= 4:
                break

            # 确保提取标准词表的原型为小写集合
            wordlist_lemmas = set(wl_df['lemma'].str.lower().str.strip())
            # 计算用户见过的词与标准词表的交集
            intersection = text_lemmas & wordlist_lemmas

            coverage = (len(intersection) / len(wordlist_lemmas) * 100 if wordlist_lemmas else 0)

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
            if "dep_df" in data and isinstance(data["dep_df"], pd.DataFrame) and not data["dep_df"].empty:
                counts = data["dep_df"]["deprel"].value_counts()
                fig = px.bar(
                    counts, x=counts.index, y=counts.values,
                    labels={'x': 'Dependency Relation (deprel)', 'y': 'Count'},
                    title="Distribution of Dependency Relation Types in Current Book",
                    color_discrete_sequence=['#1976D2']
                )
                fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No dependency data available for this book.")

    with col2:
        if st.button("📋 Show word frequency table", key="btn_show_freq_table"):
            if user_seen_counter:
                # ── ⚡ 核心对齐修改 2：用用户当前的动态词频字典直接渲染，提速百倍 ──
                # 将内存字典瞬间转为 DataFrame，避免任何多余的 NLTK 实时处理
                display_df = pd.DataFrame(list(user_seen_counter.items()), columns=['lemma', 'frequency'])

                # 补充词表分级字段（结合加载的 COCA 词表）
                display_df['wordlist'] = 'Unknown'
                for level, wl_df in standard_wordlists.items():
                    wl_set = set(wl_df['lemma'].str.lower().str.strip())
                    # 批量打标匹配
                    mask = display_df['lemma'].str.lower().isin(wl_set)
                    display_df.loc[mask, 'wordlist'] = f'COCA_{level}'


                # 定义词表排序加权权重
                def get_wordlist_order(wl):
                    if 'COCA' in str(wl):
                        try:
                            return int(str(wl).split('_')[1])
                        except Exception:
                            pass
                    return 999999


                # 按照词表级别升序（如COCA_1排最前），同级别内按用户见过的频次降序排列
                display_df['_sort_key'] = display_df['wordlist'].apply(get_wordlist_order)
                display_df = display_df.sort_values(['_sort_key', 'frequency'], ascending=[True, False])
                display_df = display_df.drop('_sort_key', axis=1)

                # 完美大表渲染，隐藏默认索引
                st.dataframe(
                    display_df[['lemma', 'frequency', 'wordlist']],
                    use_container_width=True,
                    hide_index=True
                )
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

    log_path = get_behavior_log_path(username)
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    else:
        records = []

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
        dwell_df = pd.DataFrame(dwell_data)

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
        word_df = (
            pd.DataFrame([{
                "word":           w,
                "clicks":         s["clicks"],
                "avg_dwell_ms":   round(s["total_dwell_ms"] / s["clicks"]),
                "total_dwell_ms": round(s["total_dwell_ms"]),
            } for w, s in word_stats.items()])
            .sort_values("clicks", ascending=False).reset_index(drop=True)
        ) if word_stats else pd.DataFrame(
            columns=["word", "clicks", "avg_dwell_ms", "total_dwell_ms"])

        deprel_df = (
            pd.DataFrame([{
                "deprel":         rel,
                "label":          label_deprel(rel),
                "clicks":         s["clicks"],
                "avg_dwell_ms":   round(s["total_dwell_ms"] / s["clicks"]),
                "total_dwell_ms": round(s["total_dwell_ms"]),
            } for rel, s in deprel_stats.items()])
            .sort_values("clicks", ascending=False).reset_index(drop=True)
        ) if deprel_stats else pd.DataFrame(
            columns=["deprel", "label", "clicks", "avg_dwell_ms", "total_dwell_ms"])

        pair_df = (
            pd.DataFrame([{
                "pair":           k,
                "word":           v["word"],
                "head_lemma":     v["head_lemma"],
                "deprel":         v["deprel"],
                "clicks":         v["clicks"],
                "avg_dwell_ms":   round(v["total_dwell_ms"] / v["clicks"]),
                "total_dwell_ms": round(v["total_dwell_ms"]),
            } for k, v in pair_stats.items()])
            .sort_values("clicks", ascending=False).reset_index(drop=True)
        ) if pair_stats else pd.DataFrame(
            columns=["pair","word","head_lemma","deprel","clicks","avg_dwell_ms","total_dwell_ms"])

        # ── 指标看板 ──
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Records",              len(records))
        m2.metric("Avg dwell (ms)",
                  f"{dwell_df['dwell_ms'].mean():.0f}" if not dwell_df.empty else "—")
        m3.metric("Total clicks",         int(dwell_df["clicks"].sum()))
        m4.metric("Unique words clicked", len(word_df))
        m5.metric("Avg MDD",
                  f"{dwell_df['mdd'].mean():.2f}" if not dwell_df.empty else "—")

        # ── 五个子标签 ──
        btab1, btab2, btab3, btab4, btab5 = st.tabs([
            "⏱ Dwell time", "🔤 Words clicked",
            "🔗 Dep. relations", "🔗🔗 Dep. pairs", "📋 All records",
        ])

        with btab1:
            st.markdown("**Dwell time and MDD per sentence**")
            plot_df = dwell_df.dropna(subset=["mdd", "dwell_ms"])
            if not plot_df.empty:
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
            if not dwell_df.empty:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=dwell_df.index, y=dwell_df["dwell_ms"],
                    mode="lines+markers", name="Dwell time (ms)",
                    line=dict(color="#7F77DD", width=1.5), marker=dict(size=4),
                ))
                fig2.add_trace(go.Scatter(
                    x=dwell_df.index, y=dwell_df["mdd"],
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
            if word_df.empty:
                st.info("No word clicks recorded yet.")
            else:
                st.markdown(f"**{len(word_df)} unique words clicked**")
                fig = px.bar(
                    word_df.head(30), x="word", y="clicks",
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
            if deprel_df.empty:
                st.info("No dependency relation clicks recorded yet.")
            else:
                st.markdown(f"**{len(deprel_df)} dependency relation types triggered**")
                fig = px.bar(
                    deprel_df.head(25), x="deprel", y="clicks",
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
            if pair_df.empty:
                st.info("No dependency pair clicks recorded yet.")
            else:
                st.markdown(f"**{len(pair_df)} unique dependency pairs triggered**")
                fig = px.bar(
                    pair_df.head(25), x="pair", y="clicks",
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
                pd.DataFrame(summary_rows),
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
            st.download_button(
                label="⬇ Download full JSONL",
                data=log_path.read_bytes(),
                file_name=f"reading_behavior_{username}.jsonl",
                mime="application/jsonl",
            )
        with dl_col2:
            csv_buf = dwell_df.to_csv(index=False).encode()
            st.download_button(
                label="⬇ Download summary CSV",
                data=csv_buf,
                file_name=f"reading_summary_{username}.csv",
                mime="text/csv",
            )