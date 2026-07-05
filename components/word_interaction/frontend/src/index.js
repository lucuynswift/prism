// 改动1：删掉 import { Streamlit } from "streamlit-component-lib"
// 原因：ES Module 语法浏览器无法直接执行，改为依赖 index.html 里
//       <script src="streamlit-component-lib.js"> 注入的全局 Streamlit 对象

function onRender(event) {
  // 改动2：加空值防护，tokens 为空时不崩溃
  var args = event.detail.args || {};
  var tokens = args.tokens || [];
  var sentence_id = args.sentence_id || null;

  var container = document.getElementById("root");
  var depContainer = document.getElementById("depRelationContainer");

  if (!tokens || tokens.length === 0) {
    container.innerHTML = "<span style='color:#888;font-size:20px;'>暂无句子数据传入</span>";
    if (depContainer) depContainer.innerHTML = "";
    Streamlit.setFrameHeight(60);
    return;
  }

  container.innerHTML = tokens.map(function(t) {
    if (!t.lemma) {
      return '<span class="punct-token" style="color:#666;font-size:26px !important;">' + t.display + '</span>';
    }
    var enc = encodeURIComponent(JSON.stringify(t));
    return '<span class="word"'
      + ' data-idx="' + t.position + '"'
      + ' data-info="' + enc + '"'
      + ' style="'
      + 'color:' + (t.color || '#2c3e50') + ';'
      + 'font-weight:' + (t.is_bold ? 'bold' : 'normal') + ';'
      + 'font-style:' + (t.is_italic ? 'italic' : 'normal') + ';'
      + 'font-size:26px !important;'
      + '">'
      + t.display
      + '</span>';
  }).join(" ");

  container.querySelectorAll('.word').forEach(function(el) {

    // 左键：高亮依存关系 + 展示依存面板 + 上报 Python
    el.addEventListener('click', function() {
      // 改动3：用 data-info 取数据，避免 tokens.find 在大句子里低效查找
      var wordData;
      try { wordData = JSON.parse(decodeURIComponent(el.dataset.info)); }
      catch(e) { return; }

      clearHighlights();
      el.style.outline = '3px solid #ffb142';

      var deps = wordData.deps_info || [];
      deps.forEach(function(dep) {
        var target = container.querySelector('[data-idx="' + dep.head_position + '"]');
        if (target) target.style.outline = '3px solid #ffb142';
      });

      if (depContainer) {
        if (deps.length > 0) {
          depContainer.innerHTML = '<div class="dep-relation">'
            + '<div class="relation-title">Dependency Relations</div>'
            + deps.map(function(dep) {
                return '<div class="relation-item">'
                  + '<strong>' + wordData.display + '</strong>'
                  + '<span class="relation-deprel">' + (dep.deprel || '') + '</span>'
                  + '&#8594; <strong>' + (dep.head_lemma || '') + '</strong>'
                  + '</div>';
              }).join('')
            + '</div>';
        } else {
          depContainer.innerHTML = '<div class="dep-relation">'
            + '<div class="relation-title">Root</div>'
            + '<div class="relation-item"><strong>' + wordData.display + '</strong> is the root of this sentence.</div>'
            + '</div>';
        }
      }

      Streamlit.setComponentValue({ action: "click", word: wordData, sentence_id: sentence_id });
      updateHeight(container, depContainer);
    });

    // 右键：加入单词本 + 视觉反馈
    el.addEventListener('contextmenu', function(e) {
      e.preventDefault();
      var wordData;
      try { wordData = JSON.parse(decodeURIComponent(el.dataset.info)); }
      catch(e) { return; }

      Streamlit.setComponentValue({ action: "add_wordbook", word: wordData, sentence_id: sentence_id });

      var originalColor = el.style.color;
      el.style.color = "#e74c3c";
      setTimeout(function() { el.style.color = originalColor; }, 500);
    });
  });

  updateHeight(container, depContainer);
}

function clearHighlights() {
  document.querySelectorAll('.word').forEach(function(w) {
    w.style.outline = '';
  });
  var dep = document.getElementById('depRelationContainer');
  if (dep) dep.innerHTML = '';
}

function updateHeight(container, depContainer) {
  setTimeout(function() {
    var total = (container ? container.scrollHeight : 0)
              + (depContainer ? depContainer.scrollHeight : 0)
              + 50;
    Streamlit.setFrameHeight(Math.max(total, 130));
  }, 50);
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
Streamlit.setComponentReady();

// 改动4：console.log 移到最后，确认加载成功
console.log("word_interaction 组件已加载完成");