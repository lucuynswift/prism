// ============================================================
// 新文件：components/word_interaction/frontend/src/index.js
// 左键：高亮依存 + 通知 Python 记录点击
// 右键：弹出菜单，仅"加入单词本"一项
// ============================================================
import { Streamlit, RenderData } from "streamlit-component-lib"

function onRender(event) {
  const data = event.detail;
  const { tokens, dep_map, sentence_id } = data.args;

  const container = document.getElementById("root");
  container.innerHTML = tokens.map(t =>
    `<span class="word-token" data-position="${t.position}"
           data-info='${JSON.stringify(t)}'>${t.display}</span>`
  ).join(" ");

  container.querySelectorAll(".word-token").forEach(span => {
    const wordData = JSON.parse(span.dataset.info);

    // 左键：高亮 + 上报点击
    span.addEventListener("click", () => {
      clearHighlights(container);
      const deps = wordData.deps_info || [];
      deps.forEach(d => {
        const gov = container.querySelector(`[data-position="${d.head_position}"]`);
        if (gov) gov.classList.add("dep-governor");
      });
      Streamlit.setComponentValue({ action: "click", word: wordData, sentence_id });
    });

    // 右键：仅弹出"加入单词本"
    span.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      showMenu(e.pageX, e.pageY, wordData, sentence_id);
    });
  });

  Streamlit.setFrameHeight(400);
}

function clearHighlights(container) {
  container.querySelectorAll(".dep-governor")
    .forEach(el => el.classList.remove("dep-governor"));
}

function showMenu(x, y, wordData, sentenceId) {
  document.querySelectorAll(".ctx-menu").forEach(el => el.remove());
  const menu = document.createElement("div");
  menu.className = "ctx-menu";
  menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;background:white;
    border:1px solid #ddd;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.15);
    z-index:1000;padding:6px 12px;cursor:pointer;font-size:14px;`;
  menu.innerText = `+ 加入单词本 "${wordData.display}"`;
  menu.onclick = () => {
    Streamlit.setComponentValue({ action: "add_wordbook", word: wordData, sentence_id: sentenceId });
    menu.remove();
  };
  document.body.appendChild(menu);
  document.addEventListener("click", () => menu.remove(), { once: true });
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
Streamlit.setComponentReady();
