# 文件位置：本地 prism-main/data_loader.py
# 推送到：GitHub prism-main 仓库
# 运行在：Streamlit Cloud

# ══════════════════════════════════════════
# ★ 此文件无需填写任何信息
#   所有 URL 从 book_registry.py 传入
# ══════════════════════════════════════════

import streamlit as st
import pandas as pd
import requests
from io import StringIO
from pathlib import Path
from collections import Counter
from nltk.stem import WordNetLemmatizer
import re

CACHE_DIR = Path("/opt/prism/cache")
CACHE_DIR.mkdir(exist_ok=True)
lemmatizer = WordNetLemmatizer()


def _fetch_csv(url: str, local_path: Path) -> pd.DataFrame:
    if local_path.exists():
        return pd.read_csv(local_path)
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            local_path.write_text(resp.text, encoding="utf-8")
            return pd.read_csv(StringIO(resp.text))
        st.error(f"Download failed: {url} ({resp.status_code})")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Download error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=3600)
def load_book_from_github(slug: str, repo_url: str) -> dict:
    book_dir = CACHE_DIR / slug
    book_dir.mkdir(exist_ok=True)

    sentences_df = _fetch_csv(
        f"{repo_url}/sentences.csv",
        book_dir / "sentences.csv")
    dep_df = _fetch_csv(
        f"{repo_url}/dependencies.csv",
        book_dir / "dependencies.csv")
    freq_df = _fetch_csv(
        f"{repo_url}/lemma_frequency.csv",
        book_dir / "lemma_frequency.csv")

    if sentences_df.empty:
        return {}

    if "sentence_id" in sentences_df.columns:
        sentences_df["sentence_id"] = pd.to_numeric(
            sentences_df["sentence_id"], errors="coerce").astype("Int64")

    if not dep_df.empty and "sentence_id" in dep_df.columns:
        dep_df["sentence_id"] = pd.to_numeric(
            dep_df["sentence_id"], errors="coerce").astype("Int64")
        dep_df = dep_df[dep_df["sentence_id"].notna()]

    global_freq_dict = {}
    if not freq_df.empty and "lemma" in freq_df.columns:
        global_freq_dict = dict(zip(
            freq_df["lemma"].str.lower(), freq_df["frequency"]))

    dep_index = {}
    if not dep_df.empty and "sentence_id" in dep_df.columns:
        for sid, group in dep_df.groupby("sentence_id", sort=False):
            dep_index[sid] = group

    all_sentence_lemmas = []
    if "tokenized_sentence" in sentences_df.columns:
        for tok in sentences_df["tokenized_sentence"]:
            if pd.isna(tok):
                all_sentence_lemmas.append([])
                continue
            words  = re.findall(r'\b[a-zA-Z]+\b', str(tok).lower())
            words  = [w for w in words if len(w) > 1]
            lemmas = [lemmatizer.lemmatize(w) for w in words]
            all_sentence_lemmas.append(lemmas)
    else:
        all_sentence_lemmas = [[] for _ in range(len(sentences_df))]

    sentence_deltas = [Counter(l) for l in all_sentence_lemmas]

    return {
        "slug":                slug,
        "sentences":           sentences_df,
        "all_sentence_lemmas": all_sentence_lemmas,
        "sentence_deltas":     sentence_deltas,
        "global_freq_dict":    global_freq_dict,
        "dep_df":              dep_df,
        "dep_index":           dep_index,
    }