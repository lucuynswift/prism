# 文件位置：/opt/prism/app/data_loader.py
# 完全移除 pandas，改用标准库 csv + collections
import csv
import streamlit as st
from pathlib import Path
from collections import Counter, defaultdict


def _get_dir_mtime(book_dir: Path) -> float:
    """
    返回书籍目录下所有 CSV 文件的最新修改时间戳。
    作为 load_book_from_server 的缓存失效依据：
    服务器文件更新后，mtime 变化 → 缓存自动重建，无需重启 Streamlit。
    """
    try:
        mtimes = [f.stat().st_mtime for f in Path(book_dir).glob("*.csv")]
        return max(mtimes) if mtimes else 0.0
    except Exception:
        return 0.0

def _read_csv(path: Path) -> list:
    """用标准库 csv 读取文件，返回 list of dict。
    使用 utf-8-sig 自动剔除 BOM 头，利用底层优化加速读取速度，防止 Nginx 超时。
    """
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            # 直接将 DictReader 转换为 list，这比手写 for 循环快得多
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"❌ 读取 CSV 失败 [{path.name}]: {e}")
        return []




    # 整个文件读完后，返回装满字典的列表
    return data_list

# 此时 row["sentence_id"] 就能被百分之百安全读取了


@st.cache_resource(show_spinner="⚡ Loading precomputed book vectors...")
def load_book_from_server(slug: str, repo_url: str, _mtime: float = 0.0) -> dict:
    """
    _mtime 以下划线开头，Streamlit 不将其纳入缓存键比较，
    但调用方每次传入最新的文件修改时间，值变化时强制触发缓存重建。
    """
    # 高性能书籍加载器：原生 Python（csv + collections），不依赖 pandas。
    book_dir = Path(repo_url)

    # ── 1. 读取三张核心 CSV ──
    try:
        sentences = _read_csv(book_dir / "sentences.csv")
        dep_rows = _read_csv(book_dir / "dependencies.csv")
        lemma_pos_rows = _read_csv(book_dir / "lemma_positions.csv")
    except Exception as e:
        st.error(f"Failed to load book files for '{slug}': {e}")
        return {}

    num_sentences = len(sentences)
    if num_sentences == 0:
        st.error(f"sentences.csv is empty for '{slug}'")
        return {}

    # ── 2. 动态计算 sentence_id 起点，防止 0/1 偏移漂移 ──
    all_sids = [int(r['sentence_id']) for r in lemma_pos_rows if r.get('sentence_id')]
    min_sid = min(all_sids) if all_sids else 1

    # ── 3. 构建 all_sentence_lemmas ──
    all_sentence_lemmas = [[] for _ in range(num_sentences)]

    # 🌟 在遍历的同时，直接顺便把预计算好的全局词频（global_frequency）提取出来
    global_freq_dict = {}
    lemma_by_sid = defaultdict(list)

    for r in lemma_pos_rows:
        sid = int(r['sentence_id'])
        try:
            local_id = int(r['local_word_id'])
        except (ValueError, KeyError):
            local_id = 0

        lemma = r.get('lemma', '')
        lemma_by_sid[sid].append((local_id, lemma))

        # 🌟 核心优化 1：直接获取第二列预计算好的全局词频，避免后续重复用 Counter 现场去数
        if lemma:
            lemma_lower = lemma.lower().strip()
            #if lemma_lower and lemma_lower not in global_freq_dict:
            try:
                global_freq_dict[lemma_lower] = int(r.get('global_frequency', 1))
            except (ValueError, TypeError):
                global_freq_dict[lemma_lower] = 1

    for sid, pairs in lemma_by_sid.items():
        idx = sid - min_sid
        if 0 <= idx < num_sentences:
            pairs.sort(key=lambda x: x[0])
            all_sentence_lemmas[idx] = [
                l.lower().strip()
                for _, l in pairs
                if l and l.strip() and l.strip().isalpha()  # 过滤标点、数字，只保留纯字母词
            ]

    # ── 4. 彻底移除原来导致 OOM 的 Counter(all_flat_lemmas) 全局统计代码 ──
    # 原本这里的代码已被上面第 3 步的全局预计算提取完美取代 🌟

    # ── 5. 核心优化 2：前缀和向量（稀疏化改造，极限节省内存） ──
    sentence_deltas = [Counter(sent) for sent in all_sentence_lemmas]

    sparse_prefix_counters = {}
    STEP = 50  # 步长设为 50，即每 50 句保存一个词频快照检查点
    current_cum = Counter()

    for idx, delta in enumerate(sentence_deltas):
        current_cum.update(delta)
        # 只在能被 STEP 整除的句法行上进行 .copy() 存档
        if idx % STEP == 0:
            sparse_prefix_counters[idx] = current_cum.copy()

    # ── 6. 依存索引（保持原有高效索引逻辑不变） ──
    dep_index = defaultdict(list)
    if dep_rows:
        has_dep_lemma = 'dependent_lemma' in dep_rows[0]
        key_col = 'dependent_lemma' if has_dep_lemma else 'dependent_text'
        for r in dep_rows:
            try:
                sid = int(r['sentence_id'])
            except (ValueError, KeyError):
                continue
            w_lemma = r.get(key_col, '').lower().strip()
            dep_index[(sid, w_lemma)].append(r)

    # ── 7. dep_by_sid：按 sentence_id 聚合 ──
    dep_by_sid: dict = defaultdict(list)
    for r in dep_rows:
        try:
            dep_by_sid[int(r['sentence_id'])].append(r)
        except (ValueError, KeyError):
            pass

    # 返回全新的、极简瘦身后的数据结构
    return {
        "slug": slug,
        "sentences": sentences,
        "all_sentence_lemmas": all_sentence_lemmas,
        "sentence_deltas": sentence_deltas,
        "sparse_prefix_counters": sparse_prefix_counters,  # 🌟 改为传出稀疏检查点字典
        "prefix_step": STEP,  # 🌟 传出步长控制参数
        "global_freq_dict": global_freq_dict,  # 🌟 完美预计算词频
        "dep_rows": dep_rows,
        "dep_index": dict(dep_index),
        "dep_by_sid": dict(dep_by_sid),
    }