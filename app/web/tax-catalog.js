// 全税表查询不调用匹配或 AI，不改动原始工作簿。
let catalogParent = '';
let catalogOffset = 0;
let catalogPage = null;
let catalogSelected = null;
let catalogVersion = 0;
let catalogDetailVersion = 0;
let catalogTimer = null;
let catalogReturnFocus = null;
let catalogLoading = false;

function catalogButtons() {
  $('#catalog-prev').disabled = catalogLoading || blocking > 0 || !catalogPage || catalogPage.offset === 0;
  $('#catalog-next').disabled = catalogLoading || blocking > 0 || !catalogPage || catalogPage.offset + catalogPage.page_size >= catalogPage.total;
  $('#catalog-copy').disabled = !catalogSelected?.is_leaf;
  $('#catalog-apply').disabled = catalogLoading || !catalogSelected?.is_leaf || !$('#catalog-target').value || blocking > 0;
  $('#catalog-list').querySelectorAll('button').forEach(button => { button.disabled = catalogLoading || blocking > 0; });
}
function catalogMessage(message, error = false) {
  $('#catalog-message').textContent = message;
  $('#catalog-message').className = `notice${error ? ' error' : ''}`;
}
function clearCatalogDetail() {
  catalogSelected = null; catalogDetailVersion++;
  $('#catalog-detail-name').textContent = '选择分类查看详情';
  $('#catalog-code').value = ''; $('#catalog-kind').textContent = '';
  $('#catalog-detail-path').textContent = '';
  $('#catalog-description').textContent = '选择条目查看完整说明；点击“查看下级”逐层浏览。';
  catalogButtons();
}
async function openTaxCatalog(rowId = null) {
  catalogReturnFocus = document.activeElement;
  catalogParent = ''; catalogOffset = 0; catalogSelected = null;
  catalogDetailVersion++;
  $('#catalog-query').value = ''; $('#catalog-leaf-only').checked = false;
  $('#catalog-target').innerHTML = '<option value="">仅查询，不应用</option>' + state.items.map((item, index) =>
    `<option value="${item.row_id}">第 ${index + 1} 行 · ${escapeHtml(item.name || '未命名商品')}</option>`).join('');
  $('#catalog-target').value = rowId === null ? '' : String(rowId);
  $('#catalog-detail-name').textContent = '选择分类查看详情';
  $('#catalog-code').value = '';
  $('#catalog-kind').textContent = '';
  $('#catalog-detail-path').textContent = '';
  $('#catalog-description').textContent = '选择条目查看完整说明；点击“查看下级”逐层浏览。';
  $('#tax-catalog').showModal();
  $('#catalog-query').focus();
  await loadCatalog();
}
async function loadCatalog() {
  const version = ++catalogVersion;
  catalogLoading = true;
  clearCatalogDetail();
  catalogMessage('正在读取本地税编表…');
  try {
    const page = await api().browse_tax_catalog($('#catalog-query').value, catalogParent, catalogOffset, 60, $('#catalog-leaf-only').checked);
    if (version !== catalogVersion || !$('#tax-catalog').open) return;
    catalogPage = page; catalogOffset = page.offset;
    $('#catalog-roots').innerHTML = '<button type="button" data-parent="">全部分类</button>' + page.roots.map(entry => `<button type="button" data-parent="${escapeHtml(entry.code)}">${escapeHtml(entry.name)}</button>`).join('');
    $('#catalog-roots').querySelectorAll('button').forEach(button => {
      button.classList.toggle('active', button.dataset.parent === (page.path[0]?.code || ''));
    });
    $('#catalog-path').innerHTML = '<button type="button" data-parent="">全部</button>' + page.path.map(entry => `<span> / </span><button type="button" data-parent="${escapeHtml(entry.code)}">${escapeHtml(entry.name)}</button>`).join('');
    $('#catalog-count').textContent = `${page.total} 个条目 · 完整税表共 ${page.entry_count} 项`;
    $('#catalog-list').innerHTML = page.items.length ? page.items.map(entry => `<div class="catalog-entry"><button type="button" class="catalog-select" data-code="${escapeHtml(entry.code)}"><strong>${escapeHtml(entry.display)}</strong><span class="candidate-code">${escapeHtml(entry.code)}</span><span class="muted">${entry.is_leaf ? '具体商品 · 可选' : '汇总分类 · 不可用于开票'}</span></button>${entry.children_count ? `<button type="button" class="button ghost small catalog-drill" data-parent="${escapeHtml(entry.code)}">查看下级 →</button>` : ''}</div>`).join('') : '<p class="muted">没有匹配项，可返回“全部分类”或更换关键词。</p>';
    $('#catalog-page').textContent = page.total ? `${page.offset + 1}–${Math.min(page.offset + page.page_size, page.total)} / ${page.total}` : '0 项';
    catalogMessage('分类与说明来自本地税表，未经过自动推荐筛选。');
    catalogLoading = false;
    catalogButtons();
  } catch (error) {
    if (version === catalogVersion) {
      catalogLoading = false; catalogPage = null; $('#catalog-list').innerHTML = '';
      catalogMessage(String(error), true); catalogButtons();
    }
  }
}
async function selectCatalogDetail(code) {
  const version = ++catalogDetailVersion;
  try {
    const detail = await api().tax_catalog_detail(code);
    if (version !== catalogDetailVersion || !$('#tax-catalog').open) return;
    catalogSelected = detail;
    $('#catalog-detail-name').textContent = detail.display;
    $('#catalog-code').value = detail.code;
    $('#catalog-kind').textContent = detail.is_leaf ? '具体商品，可选择此税号' : '汇总分类，请进入下级选择具体商品';
    $('#catalog-detail-path').textContent = detail.path.map(entry => entry.name).join(' / ');
    $('#catalog-description').textContent = detail.desc || '税表未提供说明，请按完整分类名称判断。';
    $('#catalog-list').querySelectorAll('.catalog-select').forEach(button => button.classList.toggle('active', button.dataset.code === detail.code));
    catalogButtons();
  } catch (error) { catalogMessage(String(error), true); }
}
$('#browse-tax-table').addEventListener('click', () => { if (ready) openTaxCatalog(); });
$('#catalog-close').addEventListener('click', () => $('#tax-catalog').close());
$('#tax-catalog').addEventListener('close', () => {
  catalogVersion++; catalogDetailVersion++; clearTimeout(catalogTimer);
  if (catalogReturnFocus?.isConnected) catalogReturnFocus.focus();
});
$('#catalog-target').addEventListener('change', catalogButtons);
$('#catalog-search').addEventListener('click', () => { clearTimeout(catalogTimer); catalogOffset = 0; loadCatalog(); });
$('#catalog-query').addEventListener('input', () => {
  clearTimeout(catalogTimer);
  catalogVersion++; catalogLoading = true;
  clearCatalogDetail();
  catalogTimer = setTimeout(() => { catalogOffset = 0; loadCatalog(); }, 220);
});
$('#catalog-query').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); $('#catalog-search').click(); }
});
$('#catalog-leaf-only').addEventListener('change', () => { catalogOffset = 0; loadCatalog(); });
$('#catalog-prev').addEventListener('click', () => { catalogOffset = Math.max(0, catalogOffset - 60); loadCatalog(); });
$('#catalog-next').addEventListener('click', () => { catalogOffset += 60; loadCatalog(); });
$('#tax-catalog').addEventListener('click', event => {
  const parent = event.target.closest('[data-parent]');
  if (parent) { catalogParent = parent.dataset.parent; catalogOffset = 0; $('#catalog-query').value = ''; clearTimeout(catalogTimer); loadCatalog(); }
  const item = event.target.closest('.catalog-select');
  if (item) selectCatalogDetail(item.dataset.code);
});
$('#catalog-list').addEventListener('keydown', event => {
  const items = [...$('#catalog-list').querySelectorAll('.catalog-select')];
  const index = items.indexOf(document.activeElement);
  if (index >= 0 && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault(); items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  }
});
$('#catalog-copy').addEventListener('click', async () => {
  if (!catalogSelected?.is_leaf) return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(catalogSelected.code);
    else { $('#catalog-code').select(); if (!document.execCommand('copy')) throw new Error('请选中税号后按 Ctrl+C 复制'); }
    catalogMessage('具体税号已复制');
  } catch (error) { $('#catalog-code').select(); catalogMessage('可选中税号后按 Ctrl+C 复制', true); }
});
$('#catalog-apply').addEventListener('click', () => {
  const detail = catalogSelected;
  const rowId = Number($('#catalog-target').value);
  if (!detail?.is_leaf || !rowId) return;
  run(async () => {
    try {
      await flushEdits();
      const result = await api().select_tax(rowId, detail.code);
      if (!result.ok) { catalogMessage(result.message, true); return; }
      accept(result.state); $('#tax-catalog').close(); notice('已从完整税表选择并确认税编');
    } catch (error) { catalogMessage(String(error), true); }
  });
});
