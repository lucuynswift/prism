# 文件位置：/opt/prism/app/data_loader.py
import streamlit as st
import pandas as pd
from pathlib import Path
from collections import Counter
import re
import pickle  # 👈 引入 pickle 库，用于实现本地硬缓存

#lemmatizer = WordNetLemmatizer()


@st.cache_resource(show_spinner="⚡ Loading precomputed book vectors...")
def load_book_from_server(slug: str, repo_url: str) -> dict:
    """
    重构后的高性能加载器：
    利用预计算的 lemma_positions.csv 和新版 dependencies.csv，
    免去全部 NLTK 还原、切词与动态词频计算逻辑。
    """
    book_dir = Path(repo_url)

    # 1. 加载核心数据表
    try:
        sentences_df = pd.read_csv(book_dir / "sentences.csv")
        dep_df = pd.read_csv(book_dir / "dependencies.csv")
        lemma_pos_df = pd.read_csv(book_dir / "lemma_positions.csv")
    except Exception as e:
        st.error(f"Failed to load book files for {slug}: {e}")
        return {}

    # 2. ⚡ 从 lemma_positions 秒级构建 all_sentence_lemmas
    # ⚡ 建立动态索引对齐基准，防范 0/1 起始点漂移
    min_sid = int(lemma_pos_df['sentence_id'].min())
    num_sentences = len(sentences_df)
    all_sentence_lemmas = [[] for _ in range(num_sentences)]

    for (sid, s_text), group in lemma_pos_df.groupby(['sentence_id', 'original_text']):
        # ✅ 动态计算绝对偏移量，替代硬编码的 sid - 1
        idx = int(sid) - min_sid

        if 0 <= idx < num_sentences:
            sorted_group = group.sort_values('local_word_id')
            lemmas_list = sorted_group['lemma'].astype(str).str.lower().str.strip().tolist()
            all_sentence_lemmas[idx] = lemmas_list
    # # 按 sentence_id 分组，直接按词的位置顺序把 lemma 组合起来
    # # 为了防止某些句子在词表中没有单词导致错位，我们预先对整个书的长度进行初始化

    # 3. ⚡ 从大表秒级提取全局静态词频字典
    # 因为 lemma_positions.csv 里已经算好了每一行的 global_frequency

    global_freq_dict = {}  # 👈 让他变成纯局部变量，受缓存保护
    if not lemma_pos_df.empty:
        counts = lemma_pos_df['lemma'].astype(str).str.lower().str.strip().value_counts()
        global_freq_dict = counts.to_dict()

    # 4. [保留核心结构]：根据预计算的列表快速生成前缀和向量
    sentence_deltas = [Counter(l) for l in all_sentence_lemmas]
    prefix_counters = []
    current_cum = Counter()
    for delta in sentence_deltas:
        prefix_counters.append(current_cum.copy())
        current_cum.update(delta)

    # 5. 构建依存树的快速索引加速匹配
    # ✅ 高性能向量化构建核心字典索引
    dep_index = {}
    if not dep_df.empty:
        # 动态探测核心键（兼容 dependent_lemma 和 dependent_text）
        key_col = 'dependent_lemma' if 'dependent_lemma' in dep_df.columns else 'dependent_text'
        dep_df['_key_lemma'] = dep_df[key_col].astype(str).str.lower().str.strip()

        # 强制将 sentence_id 转为标准 Python int，防止 numpy.int64 引发 JSON 序列化报错
        dep_df['sentence_id'] = dep_df['sentence_id'].astype(int)

        # 利用 Pandas 内部优化过的 groupby 快速分流
        for (sid, w_lemma), group in dep_df.groupby(['sentence_id', '_key_lemma']):
            # 一次性将整个子集 Dataframe 转换为 字典列表，零循环开销
            dep_index[(sid, w_lemma)] = group.drop(columns='_key_lemma').to_dict('records')

        # 清理临时计算列
        dep_df.drop(columns='_key_lemma', inplace=True)
    # dep_index = {}
    # if not dep_df.empty:
    #     # 使用重构后带 dependent_lemma 列的依赖表
    #     for _, row in dep_df.iterrows():
    #         sid = int(row['sentence_id'])
    #         # 兼容处理：优先使用 dependent_lemma，没有则降级使用小写的 text
    #         w_lemma = str(row['dependent_lemma']).lower() if 'dependent_lemma' in row else str(
    #             row['dependent_text']).lower()
    #         dep_index.setdefault((sid, w_lemma), []).append(dict(row))

    # 组装返回原系统完全一致的数据结构，确保前端 app.py 零报错缝合
    return {
        "slug": slug,
        "sentences": sentences_df,
        "all_sentence_lemmas": all_sentence_lemmas,
        "sentence_deltas": sentence_deltas,
        "prefix_counters": prefix_counters,
        "global_freq_dict": global_freq_dict,
        "dep_df": dep_df,
        "dep_index": dep_index,
    }
    # # ══════════════════════════════════════════════════════
    # # 🔥 核心优化：将计算好的巨大字典直接用二进制“死死冻结”在硬盘里
    # # ══════════════════════════════════════════════════════
    # try:
    #     with open(cache_file, "wb") as f:
    #         pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
    # except Exception as e:
    #     st.warning(f"无法写入本地硬缓存: {e}")
    #
    # return result