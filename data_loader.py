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
def load_book_from_server(slug: str, repo_url: str, mtime: float = 0.0) -> dict:
    """
    ✅ 修复：mtime 不再以下划线开头。
    Streamlit 的 cache_resource/cache_data 会把「下划线开头」的参数
    直接排除在缓存键之外——也就是说它们的值无论怎么变，都不会触发缓存重建。
    之前这里叫 _mtime，本意是想靠它的变化强制刷新缓存，
    结果恰好被 Streamlit 的这条规则完全反向作用：缓存一旦建立就永远不会失效，
    服务器上的 CSV 更新了也没用，只能重启 Streamlit 进程才能看到新数据。
    去掉下划线后，mtime 正常参与缓存键计算，文件一变、哈希就变、
    缓存自动重建，不用重启进程。
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

    # ── 3. 构建核心字典：全书词频统计 与 O(1) 前端查表 ──
    all_sentence_lemmas = [[] for _ in range(num_sentences)]
    global_freq_dict = {}
    lemma_by_sid = defaultdict(list)

    # ✨ 核心新增：专门给前端 TAB 1 准备的 O(1) 位置-频次映射表
    # 结构：{ sentence_id: { local_word_id: freq } }
    lemma_freq_by_pos = defaultdict(dict)

    for r in lemma_pos_rows:
        try:
            sid = int(r['sentence_id'])
            local_id = int(r['local_word_id'])
        except (ValueError, KeyError):
            continue

        lemma = r.get('lemma', '')
        lemma_by_sid[sid].append((local_id, lemma))

        # 🌟 提取预计算好的动态词频
        try:
            freq = int(r.get('global_frequency', 1))
        except (ValueError, TypeError):
            freq = 1

        # 组装给前端的 O(1) 字典（前提：这里的 local_id 需要和 frontend 的 split_idx 对齐，通常都是 0-based）
        lemma_freq_by_pos[sid][local_id] = freq

        # 🌟 计算全书最终词频（供 TAB 3 词汇宇宙使用）
        # 既然 freq 是动态累积的，那么只要不断取最大值，循环结束时它自然就是该词在全书的总频次！
        if lemma:
            lemma_lower = lemma.lower().strip()
            global_freq_dict[lemma_lower] = max(global_freq_dict.get(lemma_lower, 0), freq)

    # 提取并过滤纯字母组成的 all_sentence_lemmas
    for sid, pairs in lemma_by_sid.items():
        idx = sid - min_sid
        if 0 <= idx < num_sentences:
            pairs.sort(key=lambda x: x[0])
            all_sentence_lemmas[idx] = [
                l.lower().strip()
                for _, l in pairs
                if l and l.strip() and l.strip().isalpha()
            ]

    # ── 4. 🧹 彻底移除旧版累加逻辑 ──
    # 删除了原来臃肿的 sentence_deltas
    # 删除了原来吃内存的 sparse_prefix_counters
    # 我们用轻量级的 lemma_freq_by_pos 完美取代了它们！

    # ── 5. 依存索引（保持原有高效索引逻辑不变） ──
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

    # ── 6. dep_by_sid：按 sentence_id 聚合 ──
    dep_by_sid: dict = defaultdict(list)
    for r in dep_rows:
        try:
            dep_by_sid[int(r['sentence_id'])].append(r)
        except (ValueError, KeyError):
            pass

    # ── 7. 将准备好的数据返回给 Streamlit 前端 ──
    # 返回全新的、极简瘦身后的数据结构
    return {
        "slug": slug,
        "sentences": sentences,
        "all_sentence_lemmas": all_sentence_lemmas,

        # ❌ 彻底移除这三个旧的内存刺客：
        # "sentence_deltas": sentence_deltas,
        # "sparse_prefix_counters": sparse_prefix_counters,
        # "prefix_step": STEP,

        # ✅ 换成这个神级优化字典（它记录了每一句、每一个单词位置对应的预计算词频）：
        "lemma_positions": lemma_freq_by_pos,

        "global_freq_dict": global_freq_dict,
        "dep_rows": dep_rows,
        "dep_index": dict(dep_index),
        "dep_by_sid": dict(dep_by_sid),
    }
