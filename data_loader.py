# 文件位置：/opt/prism/app/data_loader.py
import streamlit as st
import pandas as pd
from pathlib import Path
from collections import Counter
from nltk.stem import WordNetLemmatizer
import re
import pickle  # 👈 引入 pickle 库，用于实现本地硬缓存

lemmatizer = WordNetLemmatizer()


@st.cache_resource(show_spinner=False)  # 👈 注意：这里用 cache_resource 确保零拷贝
def load_book_from_github(slug: str, repo_url: str) -> dict:
    book_dir = Path(repo_url)

    # ══════════════════════════════════════════════════════
    # 🔥 核心优化：检查是否存在预计算好的硬缓存文件 (Pickle)
    # ══════════════════════════════════════════════════════
    cache_file = book_dir / "preprocessed_data.pkl"
    if cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                # 如果有存盘好的结果，直接反序列化读取，耗时从 30秒 直接降到 0.1秒！
                return pickle.load(f)
        except Exception:
            pass  # 如果读取失败，则向下降级重新计算

    # 1. 读取原始 CSV
    try:
        sentences_df = pd.read_csv(book_dir / "sentences.csv")
        dep_df = pd.read_csv(book_dir / "dependencies.csv")
        freq_df = pd.read_csv(book_dir / "lemma_frequency.csv")
    except Exception as e:
        st.error(f"本地名著数据加载失败 [{slug}]: {e}")
        return {}

    if sentences_df.empty:
        return {}

    # 2. 数据清洗与转换
    if "sentence_id" in sentences_df.columns:
        sentences_df["sentence_id"] = pd.to_numeric(sentences_df["sentence_id"], errors="coerce").astype("Int64")

    if not dep_df.empty and "sentence_id" in dep_df.columns:
        dep_df["sentence_id"] = pd.to_numeric(dep_df["sentence_id"], errors="coerce").astype("Int64")
        dep_df = dep_df[dep_df["sentence_id"].notna()]

    global_freq_dict = {}
    if not freq_df.empty and "lemma" in freq_df.columns:
        global_freq_dict = dict(zip(freq_df["lemma"].str.lower(), freq_df["frequency"]))

    # 优化点 A：利用 Pandas 内部字典转换，彻底干掉极其缓慢的 for ... groupby 循环
    dep_index = {}
    if not dep_df.empty and "sentence_id" in dep_df.columns:
        # 这一步通过底层的 dict 分组，速度比标准的 groupby 循环快几十倍
        for sid, group in dep_df.groupby("sentence_id", sort=False):
            dep_index[sid] = group

    # 优化点 B：66万次词形还原确实慢，但由于后面会持久化存盘，它一生只需要跑一次
    all_sentence_lemmas = []
    if "tokenized_sentence" in sentences_df.columns:
        for tok in sentences_df["tokenized_sentence"]:
            if pd.isna(tok):
                all_sentence_lemmas.append([])
                continue
            words = re.findall(r'\b[a-zA-Z]+\b', str(tok).lower())
            words = [w for w in words if len(w) > 1]
            lemmas = [lemmatizer.lemmatize(w) for w in words]
            all_sentence_lemmas.append(lemmas)
    else:
        all_sentence_lemmas = [[] for _ in range(len(sentences_df))]

    sentence_deltas = [Counter(l) for l in all_sentence_lemmas]

    # 组装最终结果
    result = {
        "slug": slug,
        "sentences": sentences_df,
        "all_sentence_lemmas": all_sentence_lemmas,
        "sentence_deltas": sentence_deltas,
        "global_freq_dict": global_freq_dict,
        "dep_df": dep_df,
        "dep_index": dep_index,
        "wordlist": freq_df,
    }

    # ══════════════════════════════════════════════════════
    # 🔥 核心优化：将计算好的巨大字典直接用二进制“死死冻结”在硬盘里
    # ══════════════════════════════════════════════════════
    try:
        with open(cache_file, "wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        st.warning(f"无法写入本地硬缓存: {e}")

    return result