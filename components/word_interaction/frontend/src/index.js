console.log("组件 JS 已成功执行！");
console.log("组件已加载，开始执行渲染逻辑...");
import { Streamlit } from "streamlit-component-lib"

function onRender(event) {
  const { tokens, sentence_id } = event.detail.args;
  const container = document.getElementById("root");
  const depContainer = document.getElementById("depRelationContainer");

  container.innerHTML = tokens.map(t => 
    `<span class="word" data-idx="${t.position}" style="color:${t.color}; font-weight:${t.is_bold?'bold':'normal'}; font-style:${t.is_italic?'italic':'normal'};">
       ${t.display}
     </span>`
  ).join(" ");

  container.querySelectorAll('.word').forEach(el => {
    // 左键点击：显示依存关系
    el.addEventListener('click', function() {
      const idx = parseInt(this.dataset.idx);
      const data = tokens.find(t => t.position === idx);
      if (!data) return;

      clearHighlights();
      this.style.outline = '3px solid #39FF14';
      data.deps_info.forEach(dep => {
        const target = container.querySelector(`[data-idx="${dep.head_position}"]`);
        if (target) target.style.outline = '3px solid #39FF14';
      });

      if (data.deps_info.length > 0) {
        depContainer.innerHTML = `
          <div class="dep-relation">
            <div class="relation-title">Dependency relations:</div>
            ${data.deps_info.map(dep => `
              <div class="relation-item">
                <strong>${data.display}</strong> ──${dep.deprel}──> <strong>${dep.head_lemma}</strong>
              </div>
            `).join('')}
          </div>
        `;
      }
      Streamlit.setComponentValue({ action: "click", word: data, sentence_id });
    });

    // 右键点击：加入单词本 (新增逻辑)
    el.addEventListener('contextmenu', function(e) {
      e.preventDefault();
      const idx = parseInt(this.dataset.idx);
      const data = tokens.find(t => t.position === idx);
      if (!data) return;
      
      // 直接触发加入单词本，无需额外确认
      Streamlit.setComponentValue({ action: "add_wordbook", word: data, sentence_id: sentence_id });
      
      // 给用户一个简单的视觉反馈
      const originalColor = this.style.color;
      this.style.color = "red";
      setTimeout(() => this.style.color = originalColor, 500);
    });
  });
}

function clearHighlights() {
  document.querySelectorAll('.word').forEach(w => w.style.outline = '');
  document.getElementById('depRelationContainer').innerHTML = '';
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
Streamlit.setComponentReady();