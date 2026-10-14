<template>
  <div class="qf-page">
    <AppHeader title="QI Finish Rolls" active="qi-finish-rolls" :username="auth.username" :designation="auth.designation" :show-back="true" />

    <div class="qf-content">
      <!-- Search + actions -->
      <div class="qf-toolbar">
        <div class="qf-search">
          <span class="qf-search__icon">🔍</span>
          <input v-model="search" class="qf-search__input"
            placeholder="QI Report, Roll No, Lot, Batch, Item — or scan sticker"
            @keydown.enter="reload" />
        </div>
        <button class="qf-btn qf-btn--outline qf-btn--sm" @click="openCameraScanner">📷 Scan</button>
        <button
          class="qf-btn qf-btn--outline qf-btn--sm"
          v-if="selected.size"
          :disabled="printing"
          @click="printSelected"
        >
          <span v-if="printing" class="qf-spinner qf-spinner--sm"></span>
          🖨 Print Selected ({{ selected.size }})
        </button>
        <button class="qf-btn qf-btn--ghost qf-btn--sm" v-if="selected.size" @click="clearSelection">Clear</button>
      </div>

      <div class="qf-error" v-if="listError">⚠ {{ listError }}</div>
      <div class="qf-error" v-if="printError">⚠ {{ printError }}</div>

      <!-- Select-all-matching banner -->
      <div class="qf-banner" v-if="selectAllError">⚠ {{ selectAllError }}</div>
      <div class="qf-banner" v-else-if="selectingAll">
        <span class="qf-spinner qf-spinner--sm"></span> Selecting all {{ total }} rolls…
      </div>
      <div class="qf-banner" v-else-if="allMatchingInfo">
        {{ allMatchingInfo }}
        <button class="qf-link-btn" @click="clearSelection">Clear selection</button>
      </div>
      <div class="qf-banner" v-else-if="canSelectAllMatching">
        All {{ rows.length }} rolls on this page are selected.
        <button class="qf-link-btn" @click="selectAllMatching">Select all {{ total }} rolls matching “{{ search.trim() }}”</button>
      </div>

      <div class="qf-card" v-if="rows.length || listLoading">
        <div class="qf-summary" v-if="!listLoading">
          {{ total }} roll{{ total === 1 ? '' : 's' }}
          <span v-if="matchMode === 'exact'"> · exact match</span>
          <span v-else-if="matchMode === 'qr'"> · scanned sticker</span>
        </div>
        <div class="qf-table-wrap">
          <table class="qf-table">
            <thead>
              <tr>
                <th class="qf-td-checkbox">
                  <input type="checkbox" :checked="allOnPageSelected" @change="toggleSelectAllOnPage" />
                </th>
                <th>Roll No</th>
                <th>QI Report</th>
                <th>Item</th>
                <th>Fabric</th>
                <th>Lot No</th>
                <th>Batch</th>
                <th>Weight</th>
                <th>Width</th>
                <th>GSM</th>
                <th>Grade</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="listLoading">
                <td colspan="12" class="qf-td-center"><span class="qf-spinner"></span> Loading…</td>
              </tr>
              <template v-else>
                <tr v-for="r in rows" :key="r.row_id" class="qf-row" @click="toggleSelect(r)">
                  <td class="qf-td-checkbox" @click.stop>
                    <input type="checkbox" :checked="selected.has(r.row_id)" @change="toggleSelect(r)" />
                  </td>
                  <td class="qf-td-bold">{{ r.roll_no }}</td>
                  <td class="qf-td-sm">{{ r.qi_report }}</td>
                  <td class="qf-td-sm">{{ r.item_code }}</td>
                  <td class="qf-td-sm">{{ r.fabric || '—' }}</td>
                  <td class="qf-td-sm">{{ r.lot_no || '—' }}</td>
                  <td class="qf-td-sm">{{ r.batch_no }}</td>
                  <td class="qf-td-num">{{ fmtWeight(r.roll_weight) }}</td>
                  <td class="qf-td-sm">{{ r.width || '—' }}</td>
                  <td class="qf-td-sm">{{ r.gsm || '—' }}</td>
                  <td class="qf-td-sm">{{ r.grade || '—' }}</td>
                  <td @click.stop>
                    <button class="qf-icon-btn" title="Print sticker" @click="printRows([r])">🖨</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div class="qf-pagination" v-if="!listLoading">
          <button class="qf-btn qf-btn--ghost qf-btn--sm" :disabled="page === 0" @click="goPage(page - 1)">← Prev</button>
          <span class="qf-page-info">Page {{ page + 1 }} of {{ pageCount }}</span>
          <button class="qf-btn qf-btn--ghost qf-btn--sm" :disabled="page + 1 >= pageCount" @click="goPage(page + 1)">Next →</button>
        </div>
      </div>

      <div class="qf-empty" v-else-if="!listLoading">
        <div style="font-size:40px">🧾</div>
        <div>No submitted QI rolls found{{ search.trim() ? ` for “${search.trim()}”` : '' }}.</div>
      </div>
    </div>

    <!-- Camera scanner -->
    <div v-if="showScanner" class="qf-modal-overlay" @click.self="closeCameraScanner">
      <div class="qf-modal">
        <h3 class="qf-modal__title">Scan QI Roll Sticker</h3>
        <div id="qi-finish-camera-scan-region" class="qf-camera"></div>
        <div v-if="cameraError" class="qf-error" style="margin-top:12px">⚠ {{ cameraError }}</div>
        <button class="qf-btn qf-btn--ghost qf-btn--full" style="margin-top:14px" @click="closeCameraScanner">Cancel</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AppHeader from '@/components/AppHeader.vue'
import { call } from '@/api/frappe'
import QRCode from 'qrcode'
import { Html5Qrcode } from 'html5-qrcode'

const auth = useAuthStore()
const METHOD = 'pranera_roll.api.qi_rolls.get_qi_finish_rolls'

// ── List state ──────────────────────────────────────────────────────────────
const rows        = ref([])
const total       = ref(0)
const matchMode   = ref('all')
const search      = ref('')
const page        = ref(0)
const pageSize    = 20
const listLoading = ref(false)
const listError   = ref('')
const pageCount   = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function fetchRows() {
  listLoading.value = true
  listError.value   = ''
  try {
    const res = await call(METHOD, {
      search: search.value.trim(),
      start: page.value * pageSize,
      page_length: pageSize,
    })
    const data = res?.message ?? res
    rows.value      = data.rows || []
    total.value     = data.total || 0
    matchMode.value = data.match_mode || 'all'
  } catch (e) {
    listError.value = e.message || 'Failed to load QI rolls'
  } finally {
    listLoading.value = false
  }
}
function reload() { page.value = 0; fetchRows() }
function goPage(p) { page.value = p; fetchRows() }

// ── Selection ───────────────────────────────────────────────────────────────
// Keyed by the Roll Details row name (roll_no alone is not unique across
// QI reports). The row data is kept so printing needs no extra requests.
const selected        = ref(new Map())
const selectingAll    = ref(false)
const selectAllError  = ref('')
const allMatchingInfo = ref('')

const allOnPageSelected = computed(() =>
  rows.value.length > 0 && rows.value.every(r => selected.value.has(r.row_id))
)
const canSelectAllMatching = computed(() =>
  !!search.value.trim() && allOnPageSelected.value && total.value > rows.value.length
)

function toggleSelect(r) {
  allMatchingInfo.value = ''
  if (selected.value.has(r.row_id)) selected.value.delete(r.row_id)
  else selected.value.set(r.row_id, r)
}
function toggleSelectAllOnPage() {
  allMatchingInfo.value = ''
  if (allOnPageSelected.value) rows.value.forEach(r => selected.value.delete(r.row_id))
  else rows.value.forEach(r => selected.value.set(r.row_id, r))
}
function clearSelection() {
  selected.value.clear()
  allMatchingInfo.value = ''
  selectAllError.value = ''
}

async function selectAllMatching() {
  const q = search.value.trim()
  if (!q) return
  selectingAll.value   = true
  selectAllError.value = ''
  try {
    const res  = await call(METHOD, { search: q, all_matching: 1 })
    const data = res?.message ?? res
    ;(data.rows || []).forEach(r => selected.value.set(r.row_id, r))
    allMatchingInfo.value = `All ${(data.rows || []).length} rolls matching “${q}” are selected.` +
      (data.capped ? ` (Limited to the first ${(data.rows || []).length} — narrow the search.)` : '')
  } catch (e) {
    selectAllError.value = 'Failed to select all rolls: ' + (e.message || e)
  } finally {
    selectingAll.value = false
  }
}

// ── Sticker printing (100 mm × 80 mm) ───────────────────────────────────────
const printing   = ref(false)
const printError = ref('')

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}
function fmtWeight(w) {
  return w === null || w === undefined || w === '' ? '—' : Number(w).toFixed(3)
}
function fitSize(text, steps) {
  // steps: [[maxLen, size], ...] ascending; last entry is the fallback
  const len = String(text || '').length
  for (const [max, size] of steps) if (len <= max) return size
  return steps[steps.length - 1][1]
}

// QR = item_code#batch_no#lot_no#roll_no — the old QI sticker format the
// pick-order scan already parses (roll_source "QI Report Details").
function qrPayload(r) {
  return [r.item_code, r.batch_no, r.lot_no, r.roll_no].map(v => v ?? '').join('#')
}

async function buildSticker(r) {
  let qrImg = ''
  try {
    qrImg = await QRCode.toDataURL(qrPayload(r), { width: 320, margin: 0, errorCorrectionLevel: 'M' })
  } catch (e) { console.error('QR generation failed:', e) }

  const uom    = r.stock_uom || 'Kgs'
  const lot    = r.lot_no || r.batch_no || ''
  const lotPt  = fitSize(lot, [[7, '26pt'], [10, '20pt'], [13, '16pt'], [17, '13pt'], [999, '11pt']])
  const itemPt = fitSize(r.item_code, [[26, '14pt'], [34, '12pt'], [999, '10pt']])
  const fabPt  = fitSize(r.fabric, [[26, '13pt'], [34, '11.5pt'], [999, '10pt']])

  return `<div class="sticker">
  <div class="top">
    <div class="lot"><span style="font-size:${lotPt}">${esc(lot)}</span></div>
    <div class="qr">${qrImg ? `<img src="${qrImg}" alt="QR"/>` : ''}</div>
  </div>
  <table>
    <tr><td colspan="2" style="font-size:${itemPt}">${esc(r.item_code)}</td></tr>
    <tr><td colspan="2" style="font-size:${fabPt}">${esc(r.fabric)}</td></tr>
    <tr>
      <td class="half">R.No: ${esc(r.roll_no)}</td>
      <td class="half">Wt: ${esc(fmtWeight(r.roll_weight))}${esc(uom)}</td>
    </tr>
  </table>
</div>`
}

function stickerWindowHtml(divs) {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>QI Roll Sticker${divs.length > 1 ? 's' : ''}</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:Arial,Helvetica,sans-serif; color:#000; background:#e5e7eb; }
  .sticker { width:100mm; height:80mm; background:#fff; margin:4mm auto; padding:4mm;
             display:flex; flex-direction:column; gap:3mm; overflow:hidden; }
  .top { display:flex; gap:3mm; height:37mm; }
  .lot { flex:1; background:#000; color:#fff; display:flex; align-items:center; padding:0 4mm;
         font-weight:900; font-style:italic; letter-spacing:0.3px; overflow:hidden;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .lot span { line-height:1.1; overflow-wrap:anywhere; }
  .qr { width:37mm; display:flex; align-items:center; justify-content:center; }
  .qr img { width:35mm; height:35mm; image-rendering:pixelated; }
  table { width:100%; flex:1; border-collapse:collapse; table-layout:fixed; }
  td { border:0.4mm solid #000; text-align:center; vertical-align:middle; font-weight:700;
       padding:0.8mm 2mm; line-height:1.1; word-break:break-word; }
  td.half { width:50%; font-size:13pt; white-space:nowrap; }
  .noprint { text-align:center; padding:10px; }
  .noprint button { padding:8px 18px; margin:0 4px; border-radius:6px; border:none; cursor:pointer;
                    font-size:13px; font-weight:600; }
  .btn-p { background:#000; color:#fff; }
  .btn-c { background:#fff; color:#333; }
  @media print {
    @page { size:100mm 80mm; margin:0; }
    body { background:#fff; }
    .noprint { display:none; }
    .sticker { margin:0; page-break-after:always; break-after:page; }
    .sticker:last-of-type { page-break-after:auto; break-after:auto; }
  }
</style></head><body>
${divs.join('\n')}
<div class="noprint">
  <button class="btn-p" onclick="window.print()">🖨 Print${divs.length > 1 ? ` All (${divs.length})` : ''}</button>
  <button class="btn-c" onclick="window.close()">Close</button>
</div>
</body></html>`
}

async function printRows(list) {
  if (!list.length) return
  const w = window.open('', '_blank')
  if (!w) { alert('Allow pop-ups to print.'); return }
  printing.value   = true
  printError.value = ''
  try {
    const divs = []
    for (const r of list) divs.push(await buildSticker(r))
    w.document.write(stickerWindowHtml(divs))
    w.document.close()
  } catch (e) {
    w.close()
    printError.value = 'Failed to prepare stickers: ' + (e.message || e)
  } finally {
    printing.value = false
  }
}
function printSelected() { printRows(Array.from(selected.value.values())) }

// ── Camera scan → fills the search with the sticker's QR text ──────────────
const showScanner = ref(false)
const cameraError = ref('')
let html5QrCode = null

async function openCameraScanner() {
  cameraError.value = ''
  showScanner.value = true
  await nextTick()
  try {
    html5QrCode = new Html5Qrcode('qi-finish-camera-scan-region')
    await html5QrCode.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
      onCameraScan,
      () => {}
    )
  } catch (err) {
    cameraError.value = 'Could not access the camera: ' + (err?.message || err)
  }
}
async function stopCameraScanner() {
  if (!html5QrCode) return
  try {
    if (html5QrCode.isScanning) await html5QrCode.stop()
    html5QrCode.clear()
  } catch (err) { console.warn('Failed to stop camera scanner:', err) }
  html5QrCode = null
}
async function closeCameraScanner() {
  await stopCameraScanner()
  showScanner.value = false
}
async function onCameraScan(text) {
  await closeCameraScanner()
  clearTimeout(searchTimer)
  search.value = (text || '').trim()
}

// ── Init ────────────────────────────────────────────────────────────────────
onMounted(fetchRows)
onBeforeUnmount(stopCameraScanner)

let searchTimer = null
watch(search, () => {
  clearTimeout(searchTimer)
  allMatchingInfo.value = ''
  selectAllError.value  = ''
  searchTimer = setTimeout(reload, 400)
})
</script>

<style scoped>
.qf-page    { min-height:100vh; background:#f1f5f9; }
.qf-content { padding:16px; max-width:1200px; margin:0 auto; }

.qf-toolbar { display:flex; gap:10px; margin-bottom:14px; align-items:center; flex-wrap:wrap; }
.qf-search  { flex:1; min-width:220px; position:relative; }
.qf-search__icon  { position:absolute; left:10px; top:50%; transform:translateY(-50%); font-size:13px; pointer-events:none; }
.qf-search__input { width:100%; padding:10px 12px 10px 32px; border:1.5px solid #e2e8f0; border-radius:10px;
  font-size:14px; outline:none; background:white; font-family:inherit; box-sizing:border-box; }
.qf-search__input:focus { border-color:var(--app-primary,#0f6e56); }

.qf-btn { padding:10px 18px; border-radius:10px; border:none; font-size:13px; font-weight:600;
  cursor:pointer; font-family:inherit; display:inline-flex; align-items:center; justify-content:center; gap:6px; }
.qf-btn:disabled { opacity:0.5; cursor:not-allowed; }
.qf-btn--outline { background:white; color:var(--app-primary,#0f6e56); border:1.5px solid var(--app-primary,#0f6e56); }
.qf-btn--ghost   { background:#f8fafc; color:#64748b; border:1.5px solid #e2e8f0; }
.qf-btn--sm   { padding:7px 14px; font-size:12px; }
.qf-btn--full { width:100%; }

.qf-error  { background:#fef2f2; color:#dc2626; border-radius:8px; padding:10px 14px; font-size:13px; margin-bottom:10px; }
.qf-banner { display:flex; align-items:center; justify-content:center; gap:10px; flex-wrap:wrap; background:#eff6ff;
  color:#1e3a8a; border:1px solid #bfdbfe; border-radius:8px; padding:8px 14px; font-size:13px; margin-bottom:10px; }
.qf-link-btn { background:none; border:none; padding:0; color:#1d4ed8; font-weight:600; font-size:13px;
  text-decoration:underline; cursor:pointer; }

.qf-card { background:white; border-radius:14px; box-shadow:0 1px 4px rgba(0,0,0,0.07); overflow:hidden; }
.qf-summary { padding:10px 14px; font-size:12px; font-weight:600; color:#64748b; border-bottom:1px solid #f1f5f9; }
.qf-table-wrap { overflow-x:auto; }
.qf-table { width:100%; border-collapse:collapse; font-size:13px; }
.qf-table th { background:#f8fafc; padding:9px 12px; text-align:left; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:0.05em; color:#64748b; border-bottom:2px solid #e2e8f0; white-space:nowrap; }
.qf-table td { padding:9px 12px; border-bottom:1px solid #f1f5f9; color:#0f172a; vertical-align:middle; }
.qf-row { cursor:pointer; }
.qf-row:hover td { background:#f8fafc; }
.qf-td-bold { font-weight:800; }
.qf-td-sm   { font-size:11px; color:#475569; }
.qf-td-num  { text-align:right; font-family:monospace; font-size:12px; }
.qf-td-checkbox { width:32px; text-align:center; }
.qf-td-checkbox input { width:16px; height:16px; cursor:pointer; }
.qf-td-center { text-align:center; padding:24px; color:#94a3b8; }
.qf-icon-btn { background:#f1f5f9; border:none; border-radius:6px; width:30px; height:30px; cursor:pointer; font-size:14px; }
.qf-icon-btn:hover { background:#e2e8f0; }

.qf-pagination { display:flex; align-items:center; justify-content:center; gap:14px; padding:12px; border-top:1px solid #f1f5f9; }
.qf-page-info { font-size:13px; color:#64748b; font-weight:600; }
.qf-empty { text-align:center; padding:48px 24px; color:#94a3b8; display:flex; flex-direction:column; align-items:center; gap:8px; }

.qf-spinner { width:16px; height:16px; border:2px solid #cbd5e1; border-top-color:var(--app-primary,#0f6e56);
  border-radius:50%; display:inline-block; animation:qf-spin 0.8s linear infinite; vertical-align:middle; }
.qf-spinner--sm { width:12px; height:12px; }
@keyframes qf-spin { to { transform:rotate(360deg); } }

.qf-modal-overlay { position:fixed; inset:0; background:rgba(15,23,42,0.55); display:flex; align-items:center;
  justify-content:center; z-index:500; padding:20px; }
.qf-modal { background:#fff; border-radius:14px; padding:24px; width:100%; max-width:420px; text-align:center;
  box-shadow:0 10px 40px rgba(0,0,0,0.25); }
.qf-modal__title { font-size:16px; font-weight:700; margin:0 0 14px; }
.qf-camera { width:100%; aspect-ratio:1/1; border-radius:10px; overflow:hidden; background:#0f172a; }
.qf-camera :deep(video) { width:100% !important; height:100% !important; object-fit:cover !important; }
</style>
