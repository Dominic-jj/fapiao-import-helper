const $ = (selector, root = document) => root.querySelector(selector);
let state = {items: [], parse_errors: [], match_stats: null};
let mutationQueue = Promise.resolve();
let pending = 0;
let blocking = 0;
let ready = false;
let searchTimer = null;
let searchVersion = 0;
let aiEnabledDraft = null;
let rawTimer = null;
let rawQueue = Promise.resolve();
let productDraft = false;
const aiRunning = new Set();

function api() { return window.pywebview.api; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function sourceLabel(source) {
  return ({confirmed_context:'我的确认库', confirmed:'人工映射', history:'历史商品', hardware_rule:'五金词库',
    alias:'本地别名', tax_list:'税表搜索', summary_descendant:'税表分类补充', ai_rerank:'AI 建议'})[source] || '本地候选';
}
function notice(message, error = false) {
  const el = $("#notice"); el.textContent = message || ""; el.className = `notice${error ? " error" : ""}`;
}
function controls() {
  document.querySelectorAll("button").forEach(button => { button.disabled = !ready || blocking > 0; });
  if (typeof catalogButtons === 'function' && $('#tax-catalog')?.open) catalogButtons();
}
function run(task, blockUI = true) {
  if (!ready) return;
  pending++; if (blockUI) blocking++; controls();
  const job = mutationQueue.then(task);
  mutationQueue = job.catch(error => notice(String(error), true)).finally(() => { pending--; if (blockUI) blocking--; controls(); });
  return mutationQueue;
}
function rowValues(row) {
  const values = {row_id: Number(row.dataset.id), ...Object.fromEntries([...row.querySelectorAll("[data-field]")].map(field => [field.dataset.field, field.value]))};
  values.tax_rate = values.tax_rate.trim() ? String(Number(values.tax_rate) / 100) : '';
  return values;
}
function allRows() { return [...document.querySelectorAll("#items-body tr[data-id]")].map(rowValues); }
async function flushEdits() {
  clearTimeout(rawTimer);
  await saveRawInput();
  accept(await api().update_items(allRows()));
}
function saveRawInput() {
  const text = $("#manual-input").value;
  rawQueue = rawQueue.catch(() => {}).then(() => api().save_input(text)).then(result => {
    if (result.draft_message) $("#draft-status").textContent = result.draft_message;
  }).catch(error => { $("#draft-status").textContent = `草稿保存失败：${error}`; });
  return rawQueue;
}
function taxLabel(item) {
  if (!item.tax_code) return `<div class="tax-status pending"><span class="status-dot"></span>待确认</div><div class="tax-empty">${escapeHtml(item.tax_review_reason || "请选择合适的税收分类")}</div>`;
  const confirmed = Boolean(item.tax_confirmed);
  const name = item.tax_name || item.tax_standard_name || "税收分类名称暂缺";
  const categoryName = item.tax_category || "";
  const displayName = categoryName
    ? `<span class="tax-category">*${escapeHtml(categoryName)}*</span>${escapeHtml(item.name || "")}`
    : escapeHtml(name);
  const fullName = categoryName ? `*${categoryName}*${item.name || ""}` : name;
  return `<div class="tax-result ${confirmed ? "confirmed" : "suggested"}">
    <div class="tax-result-heading"><span class="tax-status ${confirmed ? "confirmed" : "suggested"}"><span class="status-dot"></span>${confirmed ? "已确认" : "建议待确认"}</span>${!confirmed ? `<button class="confirm-suggestion" data-action="confirm-suggestion" data-id="${item.row_id}">确认建议</button>` : ""}</div>
    <div class="tax-name" title="${escapeHtml(fullName)}">${displayName}</div>
    ${categoryName && item.name ? `<div class="tax-detail-name">具体分类：${escapeHtml(name)}</div>` : ""}
    <div class="tax-code-line"><span class="tax-code">${escapeHtml(item.tax_code)}</span><span class="tax-origin">${item.tax_match_source === 'manual' ? '人工选择' : escapeHtml(sourceLabel(item.tax_match_source))}</span></div>
    ${item.tax_review_reason ? `<div class="tax-review-hint">${escapeHtml(item.tax_review_reason)}</div>` : ""}
  </div>`;
}
function render() {
  const body = $("#items-body");
  const ids = [...body.querySelectorAll("tr[data-id]")].map(row => Number(row.dataset.id));
  const changed = ids.length !== state.items.length || ids.some((id, i) => id !== state.items[i].row_id);
  if (changed || !state.items.length) {
    searchVersion++;
    if (!state.items.length) {
      body.innerHTML = '<tr><td colspan="9" class="empty">输入明细并解析后，结果会显示在这里。</td></tr>';
    } else {
      body.innerHTML = state.items.map(item => `
        <tr data-id="${item.row_id}">
          <td><input class="name" data-field="name" value="${escapeHtml(item.name)}" placeholder="物品名称"></td>
          <td><input class="spec" data-field="spec" value="${escapeHtml(item.spec)}" placeholder="规格"></td>
          <td><input data-field="unit" value="${escapeHtml(item.unit)}" placeholder="单位"></td>
          <td><input class="number" data-field="quantity" type="number" min="0" step="any" value="${item.quantity}"></td>
          <td><input class="number" data-field="unit_price" type="number" min="0" step="any" value="${item.unit_price}"></td>
          <td><span class="amount">${Number(item.amount || 0).toFixed(2)}</span></td>
          <td><input class="number" data-field="tax_rate" type="number" min="0" max="100" step="any" value="${Number(item.tax_rate || 0) * 100}"></td>
          <td class="tax-cell"><div class="tax-select"><input class="tax-search" data-search="${item.row_id}" placeholder="搜索分类名称或编码…"><button class="button ghost small" data-action="suggest" data-id="${item.row_id}">查找</button><button class="button ghost small" data-action="browse-tax" data-id="${item.row_id}">浏览表</button></div>
            <div class="current-tax"></div><button class="button ghost small ai-row" data-action="assist" data-id="${item.row_id}">AI 找候选</button><div class="tax-results" id="results-${item.row_id}"></div></td>
          <td><button class="remove" title="删除此行" data-action="remove" data-id="${item.row_id}">×</button></td>
        </tr>`).join("");
    }
  }
  // 编辑后仅更新计算值和建议，保留输入 DOM、焦点与尚未提交的键入内容。
  for (const item of state.items) {
    const row = body.querySelector(`tr[data-id="${item.row_id}"]`);
    $(".amount", row).textContent = Number(item.amount || 0).toFixed(2);
    $(".current-tax", row).innerHTML = taxLabel(item);
    $(".current-tax", row).title = [item.tax_standard_name, item.tax_review_reason, item.tax_name].filter(Boolean).join("；");
  }
  const amount = state.items.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  $("#summary").innerHTML = `<span class="summary-count">${state.items.length} 行明细</span><span class="summary-divider">·</span><span class="summary-total">合计 <strong>¥${amount.toFixed(2)}</strong></span>`;
  const stats = state.match_stats;
  const aiSummary = stats ? (stats.ai_attempted
    ? `AI 调用 ${stats.ai_attempted} · 成功 ${stats.ai_success || 0} · 回退/待复核 ${stats.ai_fallback || 0}`
    : stats.ai_available ? "AI 可用，本轮未触发" : (stats.ai_skip_reason || "AI 未启用")) : "";
  $("#match-summary").textContent = stats ? `本轮税编建议：${stats.processed}/${stats.total} · 待确认 ${stats.needs_review || 0} · 历史 ${stats.confirmed} · 规则 ${stats.rule} · ${aiSummary}` : "";
  $("#parse-errors").innerHTML = state.parse_errors?.length ? state.parse_errors.map(error => `<p>第 ${error.line_number} 行：${escapeHtml(error.raw)}；${escapeHtml(error.reason)}</p>`).join("") : "";
  renderAiSettings();
  renderProductSettings();
  $("#draft-status").textContent = state.draft_message || "";
  document.querySelectorAll('.ai-row').forEach(button => {
    button.hidden = !state.ai_available;
    button.textContent = aiRunning.has(Number(button.dataset.id)) ? '取消 AI' : 'AI 找候选';
  });
  controls();
}
function accept(result) {
  if ((result.revision ?? 0) < (state.revision ?? 0)) return;
  state = result; render();
}
function renderAiSettings() {
  const settings = state.ai_settings || {};
  const checkbox = $("#ai-enabled");
  checkbox.checked = aiEnabledDraft === null ? Boolean(settings.enabled) : aiEnabledDraft;
  const source = settings.key_source || "未配置";
  const status = !settings.enabled
    ? `已关闭 · 本地匹配和手动选择可用 · Key：${source}`
    : settings.available
      ? `已开启 · Key：${source}`
      : `已开启但不可调用 · ${settings.message || "请配置 API Key"}`;
  $("#ai-settings-status").textContent = status;
  $("#clear-ai-key").disabled = source !== "系统凭据管理器";
}

function renderProductSettings() {
  const settings = state.product_settings || {};
  if (!productDraft) {
    $('#history-dir').value = settings.history_dir || '';
    $('#industry').value = settings.industry || '';
    $('#default-tax-rate').value = Number(settings.tax_rate || 0) * 100;
    $('#price-mode').value = settings.price_mode || 'inclusive';
  }
  const stats = settings.history_stats || {};
  $('#history-status').textContent = `已读取 ${stats.files || 0} 个文件，${stats.records || 0} 条历史，${stats.conflicts || 0} 处冲突，${stats.ignored || 0} 个文件未读取${stats.errors?.length ? '；' + stats.errors.join('；') : ''}`;
  $('#export-mode').textContent = `当前单价口径：${settings.price_mode === 'exclusive' ? '不含税' : '含税'} · 官方明细导入请选择相同口径 · 开具和打印在官方系统完成`;
}
$('#toggle-product-settings').addEventListener('click', () => {
  const panel = $('#product-settings-panel');
  panel.hidden = !panel.hidden;
  $('#toggle-product-settings').setAttribute('aria-expanded', String(!panel.hidden));
});
$('#product-settings-panel').addEventListener('input', () => { productDraft = true; });
$('#choose-history').addEventListener('click', () => run(async () => {
  const result = await api().choose_history_directory();
  if (result.ok) { $('#history-dir').value = result.path; productDraft = true; }
  else if (result.message) notice(result.message, true);
}));
$('#open-history').addEventListener('click', () => run(async () => {
  const result = await api().open_history_directory();
  if (!result.ok) notice(result.message, true);
}));
$('#save-product-settings').addEventListener('click', () => run(async () => {
  await flushEdits();
  const rate = $('#default-tax-rate').value;
  if (!rate.trim()) { notice('请输入默认税率', true); return; }
  const result = await api().configure_products($('#history-dir').value, $('#industry').value, String(Number(rate) / 100), $('#price-mode').value);
  if (!result.ok) { notice(result.message, true); return; }
  productDraft = false;
  accept(result.state);
  notice('商品库和导出设置已保存；对已有自动建议应用新词库，请点击重新匹配');
}));
$('#manual-input').addEventListener('input', () => {
  if (!ready) return;
  clearTimeout(rawTimer);
  rawTimer = setTimeout(saveRawInput, 250);
});

$("#parse").addEventListener("click", () => {
  const text = $("#manual-input").value;
  run(async () => { clearTimeout(rawTimer); await rawQueue; notice("正在解析并匹配税编…"); accept(await api().parse_text(text)); notice(`处理完成，共 ${state.items.length} 行${state.parse_errors.length ? "，请修正解析失败行" : ""}`, state.parse_errors.length > 0); });
});
$("#manual-input").addEventListener("keydown", event => {
  if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); $("#parse").click(); }
});
$("#clear").addEventListener("click", () => run(async () => { clearTimeout(rawTimer); await rawQueue; accept(await api().clear_items()); $("#manual-input").value = ""; notice(""); }));
$("#add-row").addEventListener("click", () => run(async () => { await flushEdits(); accept(await api().add_item()); $("#items-body tr:last-child .name")?.focus(); }));
$("#rematch").addEventListener("click", () => run(async () => { await flushEdits(); notice("正在重新匹配…"); accept(await api().rematch()); notice("建议已更新，人工选择已保留"); }));
$("#toggle-ai-settings").addEventListener("click", () => {
  const panel = $("#ai-settings-panel"), expanded = panel.hidden;
  panel.hidden = !expanded;
  $("#toggle-ai-settings").setAttribute("aria-expanded", String(expanded));
});
$("#ai-enabled").addEventListener("change", event => { aiEnabledDraft = event.target.checked; });
$("#save-ai-settings").addEventListener("click", () => run(async () => {
  const result = await api().configure_ai($("#ai-enabled").checked, $("#ai-key").value);
  if (!result.ok) { notice(result.message, true); return; }
  $("#ai-key").value = "";
  aiEnabledDraft = null;
  accept(result.state);
  notice("AI 设置已保存；对待确认商品点击“AI 找候选”按需使用");
}));
$("#clear-ai-key").addEventListener("click", () => run(async () => {
  const result = await api().configure_ai($("#ai-enabled").checked, "", true);
  if (!result.ok) { notice(result.message, true); return; }
  aiEnabledDraft = null;
  accept(result.state);
  notice("已清除系统凭据管理器中的密钥；环境变量配置仍可使用");
}));

$("#items-body").addEventListener("change", event => {
  const input = event.target.closest("[data-field]"); if (!input) return;
  const values = rowValues(input.closest("tr"));
  run(async () => { accept(await api().update_item(values.row_id, values)); notice(""); }, false);
});
$("#items-body").addEventListener("input", event => {
  const input = event.target.closest("[data-search]"); if (!input || !ready) return;
  clearTimeout(searchTimer);
  const version = ++searchVersion, rowId = Number(input.dataset.search), query = input.value;
  searchTimer = setTimeout(async () => {
    const container = $(`#results-${rowId}`); if (!container) return;
    if (!query.trim()) { container.innerHTML = ""; return; }
    try {
      const row = input.closest('tr');
      const candidates = await api().search_tax(query, row.querySelector('[data-field=spec]').value, row.querySelector('[data-field=unit]').value);
      if (version === searchVersion && input.isConnected && input.value === query) renderCandidates(rowId, candidates);
    } catch (error) { notice(String(error), true); }
  }, 220);
});
$("#items-body").addEventListener("click", event => {
  const button = event.target.closest("[data-action]"); if (!button) return;
  const rowId = Number(button.dataset.id);
  if (button.dataset.action === 'browse-tax') openTaxCatalog(rowId);
  if (button.dataset.action === "remove") run(async () => {
    // 删除错误行也应可用，同时提交其他行的最新编辑。
    const rows = allRows().filter(row => row.row_id !== rowId);
    accept(await api().update_items(rows));
    accept(await api().remove_item(rowId));
  });
  if (button.dataset.action === "suggest") run(async () => {
    await flushEdits();
    const item = state.items.find(item => item.row_id === rowId);
    if (item?.name) renderCandidates(rowId, await api().search_tax(item.name, item.spec, item.unit));
  });
  if (button.dataset.action === "confirm-suggestion") run(async () => {
    await flushEdits();
    const item = state.items.find(item => item.row_id === rowId);
    if (!item?.tax_code) return;
    const result = await api().select_tax(rowId, item.tax_code);
    if (!result.ok) notice(result.message, true);
    else { accept(result.state); notice("税编建议已确认"); }
  });
  if (button.dataset.action === 'assist') {
    if (aiRunning.has(rowId)) {
      api().cancel_ai(rowId).then(() => notice('AI 已取消；正在发送的请求结束后会丢弃结果'));
      return;
    }
    aiRunning.add(rowId); render();
    (async () => {
      try {
        await mutationQueue;
        await flushEdits();
        const result = await api().assist_tax(rowId);
        if (result.ok) { accept(result.state); notice('AI 建议已更新，请按实际商品确认'); }
        else notice(result.message, true);
      } catch (error) { notice(String(error), true); }
      finally { aiRunning.delete(rowId); render(); }
    })();
  }
});
function renderCandidates(rowId, candidates) {
  const container = $(`#results-${rowId}`); if (!container) return;
  if (!candidates.length) { container.innerHTML = '<div class="no-candidates">没有找到候选项，请换个名称或直接输入税编搜索。</div>'; return; }
  container.innerHTML = `<div class="candidate-heading">${candidates.length} 个候选 · 方向键切换，Enter 选择，Esc 关闭</div><div class="candidate-list">${candidates.map((item, index) => `<button type="button" class="candidate ${item.requires_review ? "needs-review" : ""}" data-code="${escapeHtml(item.code)}" title="${escapeHtml(item.desc || item.review_reason || "点击采用此分类")}"><span class="candidate-index">${index + 1}</span><span class="candidate-main"><span class="candidate-name">${escapeHtml(item.display || item.name)}</span><span class="candidate-code">${escapeHtml(item.code)} · ${escapeHtml(sourceLabel(item.source))}</span>${item.review_reason ? `<span class="candidate-reason">${escapeHtml(item.review_reason)}</span>` : ""}${item.desc ? `<span class="candidate-desc">${escapeHtml(item.desc)}</span>` : ""}</span><span class="candidate-action">选用 →</span></button>`).join("")}</div>${candidates.length >= 35 && candidates.length < 200 ? '<button class="button ghost small more-candidates">更多结果</button>' : ''}`;
  container.querySelectorAll(".candidate").forEach(candidate => candidate.addEventListener("click", () => {
    const code = candidate.dataset.code;
    run(async () => {
      await flushEdits();
      const result = await api().select_tax(rowId, code);
      if (!result.ok) notice(result.message, true);
      else { accept(result.state); container.innerHTML = ""; notice("税编已更新"); }
    });
  }));
  controls();
  container.querySelector('.more-candidates')?.addEventListener('click', async () => {
    try {
      const row = container.closest('tr');
      const query = row.querySelector('.tax-search').value || row.querySelector('[data-field=name]').value;
      renderCandidates(rowId, await api().search_tax(query, row.querySelector('[data-field=spec]').value, row.querySelector('[data-field=unit]').value, 200));
    } catch (error) { notice(String(error), true); }
  });
}
$('#items-body').addEventListener('keydown', event => {
  const row = event.target.closest('tr[data-id]');
  if (!row || !event.target.matches('.tax-search,.candidate')) return;
  const container = row.querySelector('.tax-results');
  const buttons = [...container.querySelectorAll('.candidate')];
  if (event.key === 'Escape') { container.innerHTML = ''; row.querySelector('.tax-search').focus(); searchVersion++; }
  if (!buttons.length) return;
  const current = buttons.indexOf(document.activeElement);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    buttons[(current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
  } else if (event.key === 'Enter') {
    event.preventDefault(); (buttons[current] || buttons[0]).click();
  }
});
$("#save-confirmations").addEventListener("click", () => run(async () => {
  await flushEdits();
  const result = await api().save_confirmations();
  notice(result.errors.length ? result.errors.join("；") : `已保存 ${result.saved} 条税编确认`, result.errors.length > 0);
}));
$("#export").addEventListener("click", () => run(async () => {
  await flushEdits();
  notice("正在准备导出…");
  const result = await api().export_invoice();
  if (result.ok) notice(`已导出：${result.path}`);
  else notice(result.cancelled ? "" : result.message, !result.cancelled);
}));
window.addEventListener("pywebviewready", async () => {
  try { state = await api().get_state(); ready = true; $('#manual-input').value = state.raw_text || ''; render(); $("#manual-input").focus(); }
  catch (error) { notice(String(error), true); }
});
render();
