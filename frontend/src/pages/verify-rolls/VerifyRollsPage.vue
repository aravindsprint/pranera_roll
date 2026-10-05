<template>
  <div class="page">
    <AppHeader title="Verify Rolls" active="verify-rolls" :username="auth.username" :designation="auth.designation" />
    <div class="page-content">

      <!-- ── 1. Pick / scan the Material Transfer ───────────────────────── -->
      <div class="card">
        <label class="form-label">Stock Entry — Material Transfer <span class="req">*</span></label>
        <div class="se-row">
          <RemoteSelect
            class="se-select"
            :model-value="transfer?.stock_entry || ''"
            :fetcher="fetchTransfers"
            :disabled="loadingTransfer || submitting"
            placeholder="Search or scan Stock Entry..."
            @change="opt => opt && loadTransfer(opt.value)"
            @enter="loadTransfer"
          />
          <button class="btn btn-primary btn-icon" :disabled="loadingTransfer || submitting" @click="openScanner('se')" title="Scan 2D barcode">
            <i class="pi pi-qrcode"></i>
          </button>
        </div>
        <div v-if="loadingTransfer" class="hint-text"><i class="pi pi-spin pi-spinner"></i><span>Loading rolls…</span></div>
        <div v-if="loadError" class="error-banner" style="margin-top:10px">
          <i class="pi pi-exclamation-triangle"></i> {{ loadError }}
        </div>
      </div>

      <template v-if="transfer">
        <!-- ── Summary ──────────────────────────────────────────────────── -->
        <div class="card">
          <div class="sum-title">{{ transfer.stock_entry }}</div>
          <div class="sum-sub">
            Pick List {{ transfer.pick_list }}<span v-if="transfer.posting_date"> · {{ transfer.posting_date }}</span>
          </div>
          <div class="wh-row">
            <i class="pi pi-map-marker"></i>
            <span>Now in: {{ transfer.source_warehouses.join(', ') || '—' }}</span>
          </div>

          <div class="stats">
            <div class="stat" :class="{ 'stat--ok': allVerified }">
              <div class="stat__val">{{ verifiedCount }}<span>/{{ transfer.total_rolls }}</span></div>
              <div class="stat__lbl">Rolls verified</div>
            </div>
            <div class="stat" :class="{ 'stat--ok': allVerified }">
              <div class="stat__val">{{ fmt(verifiedWeight) }}<span>/{{ fmt(transfer.total_weight) }}</span></div>
              <div class="stat__lbl">Weight verified</div>
            </div>
          </div>
          <div class="progress"><div class="progress__bar" :style="{ width: progressPct + '%' }"></div></div>

          <div v-if="transfer.already_put_away" class="warn-banner">
            <i class="pi pi-info-circle"></i>
            <span>These rolls were already put away in <b>{{ transfer.already_put_away }}</b> ({{ transfer.already_put_away_status }}). You can still verify them, but a new transfer can't be created.</span>
          </div>
        </div>

        <!-- ── 2. Verify rolls ──────────────────────────────────────────── -->
        <div class="card" v-if="stage === 'verify'">
          <label class="form-label">Scan Rolls</label>
          <div class="scan-row">
            <button class="btn btn-primary btn-scan" @click="openScanner('roll')" :disabled="allVerified">
              <i class="pi pi-camera"></i><span>{{ allVerified ? 'All rolls verified' : 'Scan Rolls' }}</span>
            </button>
          </div>
          <input
            v-model="manualRoll"
            class="form-input"
            placeholder="…or type / scanner-gun a roll no and press Enter"
            autocapitalize="off" autocomplete="off" spellcheck="false"
            :disabled="allVerified"
            @keydown.enter.prevent="onManualRoll"
          />
          <div v-if="scanFlash" class="flash" :class="'flash--' + scanFlash.kind">
            <i class="pi" :class="scanFlash.kind === 'ok' ? 'pi-check-circle' : (scanFlash.kind === 'warn' ? 'pi-info-circle' : 'pi-exclamation-triangle')"></i>
            <span>{{ scanFlash.msg }}</span>
          </div>
        </div>

        <!-- Done, no transfer -->
        <div class="card done-card" v-if="stage === 'done'">
          <i class="pi pi-verified done-card__icon"></i>
          <div class="done-card__title">All {{ transfer.total_rolls }} rolls verified</div>
          <div class="done-card__sub">No Material Transfer created.</div>
          <div class="btn-row">
            <button class="btn btn-outline" v-if="!transfer.already_put_away" @click="goToBins">Create Material Transfer</button>
            <button class="btn btn-primary" @click="resetAll">Verify Another</button>
          </div>
        </div>

        <!-- ── 3. Bins (target) per roll ────────────────────────────────── -->
        <div class="card" v-if="stage === 'bins'">
          <h2 class="section-title">Select Bin for Each Roll</h2>
          <div class="hint-text">
            <i class="pi pi-info-circle"></i>
            <span>The bin is the Target Warehouse. Source Warehouse is where each roll landed on {{ transfer.stock_entry }}.</span>
          </div>

          <label class="form-label" style="margin-top:6px">Same bin for all rolls (optional)</label>
          <div class="se-row">
            <RemoteSelect
              class="se-select"
              v-model="allBin"
              :fetcher="binFetcher(transfer.source_warehouses[0])"
              placeholder="Search bin..."
            />
            <button class="btn btn-outline btn-icon" @click="openScanner('bin-all')" title="Scan bin label"><i class="pi pi-qrcode"></i></button>
            <button class="btn btn-primary btn-apply" :disabled="!allBin" @click="applyAllBin">Apply</button>
          </div>
          <div class="hint-text" style="margin-top:6px">
            <i class="pi pi-check-square"></i>
            <span>{{ binnedCount }} / {{ transfer.total_rolls }} rolls have a bin</span>
          </div>
        </div>

        <!-- ── Roll list (shared by verify + bins stages) ───────────────── -->
        <div class="card" v-if="stage !== 'done'">
          <h2 class="section-title">
            Rolls
            <span class="filter-tabs" v-if="stage === 'verify'">
              <button :class="{ on: listFilter === 'all' }" @click="listFilter = 'all'">All</button>
              <button :class="{ on: listFilter === 'pending' }" @click="listFilter = 'pending'">Not Verified ({{ transfer.total_rolls - verifiedCount }})</button>
            </span>
          </h2>
          <div class="roll-list">
            <div
              v-for="r in shownRolls" :key="r.roll_no"
              class="roll" :class="{ 'roll--ok': verified[r.roll_no], 'roll--hit': lastHit === r.roll_no }"
            >
              <div class="roll__head">
                <div class="roll__main">
                  <div class="roll__no">Roll {{ r.roll_no }}</div>
                  <div class="roll__meta">
                    {{ r.commercial_name || r.item_name || r.item_code }}<span v-if="r.color"> · {{ r.color }}</span>
                  </div>
                  <div class="roll__meta">{{ r.item_code }} · {{ r.batch || 'no batch' }}</div>
                </div>
                <div class="roll__right">
                  <div class="roll__wt">{{ weightText(r) }}</div>
                  <span class="badge" :class="verified[r.roll_no] ? 'badge--ok' : 'badge--pending'">
                    <i class="pi" :class="verified[r.roll_no] ? 'pi-check' : 'pi-clock'"></i>
                    {{ verified[r.roll_no] ? 'Verified' : 'Not Verified' }}
                  </span>
                </div>
              </div>

              <div v-if="stage === 'bins'" class="roll__bin">
                <div class="roll__from">From: {{ r.source_warehouse || '—' }}</div>
                <div class="se-row">
                  <RemoteSelect
                    class="se-select"
                    v-model="bins[r.roll_no]"
                    :fetcher="binFetcher(r.source_warehouse)"
                    placeholder="Select bin..."
                  />
                  <button class="btn btn-outline btn-icon" @click="openScanner('bin', r.roll_no)" title="Scan bin label"><i class="pi pi-qrcode"></i></button>
                </div>
                <div v-if="bins[r.roll_no] && bins[r.roll_no] === r.source_warehouse" class="mini-err">
                  Same as source — pick a different bin
                </div>
              </div>
            </div>
            <div v-if="!shownRolls.length" class="empty">All rolls verified 🎉</div>
          </div>
        </div>

        <!-- ── Submit (bins stage) ──────────────────────────────────────── -->
        <div class="card" v-if="stage === 'bins'">
          <label class="form-label">Posting Date <span class="req">*</span></label>
          <input v-model="postingDate" type="date" class="form-input" />
          <div class="btn-row" style="margin-top:14px">
            <button class="btn btn-outline" :disabled="!canSubmit || submitting" @click="submit(false)">
              <i v-if="submitting && submittingDraft" class="pi pi-spin pi-spinner"></i>
              {{ submitting && submittingDraft ? 'Saving…' : 'Save as Draft' }}
            </button>
            <button class="btn btn-primary" :disabled="!canSubmit || submitting" @click="submit(true)">
              <i v-if="submitting && !submittingDraft" class="pi pi-spin pi-spinner"></i>
              {{ submitting && !submittingDraft ? 'Submitting…' : 'Create & Submit' }}
            </button>
          </div>
          <button class="btn btn-ghost-link" :disabled="submitting" @click="stage = 'done'">Cancel — don't create a transfer</button>
          <div v-if="submitError" class="error-banner" style="margin-top:12px">
            <i class="pi pi-exclamation-triangle"></i> {{ submitError }}
          </div>
        </div>
      </template>

      <!-- ── Camera scanner ─────────────────────────────────────────────── -->
      <transition name="modal-fade">
        <div v-if="scanner.open" class="modal-overlay" @click.self="closeScanner">
          <div class="modal-box scanner-box">
            <h3 class="modal-title">{{ scannerTitle }}</h3>
            <div id="verify-camera-region" class="camera-region"></div>
            <div v-if="scanner.mode === 'roll'" class="scanner-count">
              {{ verifiedCount }} / {{ transfer?.total_rolls || 0 }} verified
            </div>
            <div v-if="scanner.mode === 'roll' && scanFlash" class="flash" :class="'flash--' + scanFlash.kind">
              <span>{{ scanFlash.msg }}</span>
            </div>
            <div v-if="scanner.error" class="error-banner" style="margin-top:12px">
              <i class="pi pi-exclamation-triangle"></i> {{ scanner.error }}
            </div>
            <button class="btn btn-outline btn-full" style="margin-top:14px" @click="closeScanner">
              {{ scanner.mode === 'roll' ? 'Done' : 'Cancel' }}
            </button>
          </div>
        </div>
      </transition>

      <!-- ── "All verified → Material Transfer?" ────────────────────────── -->
      <transition name="modal-fade">
        <div v-if="showConfirm" class="modal-overlay">
          <div class="modal-box">
            <i class="pi pi-verified modal-icon"></i>
            <h3 class="modal-title">All {{ transfer?.total_rolls }} rolls verified</h3>
            <p class="modal-msg">Do you want to create a <b>Stock Entry — Material Transfer</b> to move these rolls into bins?</p>
            <div class="btn-row">
              <button class="btn btn-outline" @click="answer(false)">No</button>
              <button class="btn btn-primary" @click="answer(true)">Yes</button>
            </div>
          </div>
        </div>
      </transition>

      <!-- ── Success ────────────────────────────────────────────────────── -->
      <transition name="modal-fade">
        <div v-if="success" class="modal-overlay">
          <div class="modal-box">
            <i class="pi pi-check-circle modal-icon"></i>
            <h3 class="modal-title">{{ success.submitted ? 'Material Transfer Submitted' : 'Material Transfer Saved as Draft' }}</h3>
            <p class="modal-msg">
              {{ success.rolls }} roll(s) moved into bins{{ success.submitted ? '' : ' — someone still needs to review and submit it' }}.
            </p>
            <div class="modal-docno">{{ success.stock_entry }}</div>
            <button class="btn btn-primary btn-full" @click="resetAll">Verify Another</button>
          </div>
        </div>
      </transition>

    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Html5Qrcode } from 'html5-qrcode'
import { useAuthStore } from '@/stores/auth'
import AppHeader from '@/components/AppHeader.vue'
import RemoteSelect from '@/components/RemoteSelect.vue'
import {
  searchMaterialTransfers, getTransferForVerification, searchBins, createVerifiedTransfer,
} from '@/api/frappe'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// ── State ───────────────────────────────────────────────────────────────────
const transfer = ref(null)          // payload from get_transfer_for_verification
const stage = ref('verify')         // 'verify' | 'done' | 'bins'
const verified = reactive({})       // roll_no -> true
const bins = reactive({})           // roll_no -> warehouse
const allBin = ref('')
const listFilter = ref('all')
const manualRoll = ref('')
const lastHit = ref('')
const scanFlash = ref(null)         // { kind: 'ok'|'warn'|'err', msg }
const loadingTransfer = ref(false)
const loadError = ref('')
const showConfirm = ref(false)
const postingDate = ref(today())
const submitting = ref(false)
const submittingDraft = ref(false)
const submitError = ref('')
const success = ref(null)

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const fmt = n => (Math.round((Number(n) || 0) * 1000) / 1000).toLocaleString('en-IN', { maximumFractionDigits: 3 })
const isWeightUom = u => /^kg|^kgs$/i.test(u || '')
function weightText(r) {
  if (isWeightUom(r.uom) || !r.uom) return `${fmt(r.roll_weight)} kg`
  return r.roll_weight && r.roll_weight !== r.qty
    ? `${fmt(r.qty)} ${r.uom} · ${fmt(r.roll_weight)} kg`
    : `${fmt(r.qty)} ${r.uom}`
}

// ── Derived ─────────────────────────────────────────────────────────────────
const rolls = computed(() => transfer.value?.rolls || [])
const verifiedCount = computed(() => rolls.value.filter(r => verified[r.roll_no]).length)
const verifiedWeight = computed(() => rolls.value.reduce((s, r) => s + (verified[r.roll_no] ? r.roll_weight : 0), 0))
const allVerified = computed(() => rolls.value.length > 0 && verifiedCount.value === rolls.value.length)
const progressPct = computed(() => rolls.value.length ? Math.round(verifiedCount.value * 100 / rolls.value.length) : 0)
const binnedCount = computed(() => rolls.value.filter(r => bins[r.roll_no]).length)
const canSubmit = computed(() =>
  allVerified.value && !transfer.value?.already_put_away &&
  rolls.value.every(r => bins[r.roll_no] && bins[r.roll_no] !== r.source_warehouse)
)
// Not-verified first, so the next roll to find is always at the top
const shownRolls = computed(() => {
  let list = rolls.value
  if (stage.value === 'verify' && listFilter.value === 'pending') list = list.filter(r => !verified[r.roll_no])
  if (stage.value !== 'verify') return list
  return [...list].sort((a, b) => (verified[a.roll_no] ? 1 : 0) - (verified[b.roll_no] ? 1 : 0))
})

// ── Progress persistence (survives refresh / app switch mid-verification) ──
const storeKey = se => `ROLL_VERIFY:${se}`
function saveProgress() {
  if (!transfer.value) return
  try {
    localStorage.setItem(storeKey(transfer.value.stock_entry), JSON.stringify({
      verified: Object.keys(verified).filter(k => verified[k]),
      bins: { ...bins },
      stage: stage.value,
      at: Date.now(),
    }))
  } catch { /* storage full / private mode — progress just won't survive a refresh */ }
}
function restoreProgress(se, rollNos) {
  try {
    const saved = JSON.parse(localStorage.getItem(storeKey(se)) || 'null')
    if (!saved || Date.now() - (saved.at || 0) > 3 * 24 * 3600 * 1000) return
    const valid = new Set(rollNos)
    for (const r of saved.verified || []) if (valid.has(r)) verified[r] = true
    for (const [r, b] of Object.entries(saved.bins || {})) if (valid.has(r) && b) bins[r] = b
    if (saved.stage === 'bins' || saved.stage === 'done') stage.value = saved.stage
  } catch { /* corrupt entry — ignore */ }
}
function clearProgress(se) { try { localStorage.removeItem(storeKey(se)) } catch { /* ignore */ } }
watch([verified, bins, stage], saveProgress, { deep: true })

// ── Load the transfer ───────────────────────────────────────────────────────
function clearState() {
  for (const k of Object.keys(verified)) delete verified[k]
  for (const k of Object.keys(bins)) delete bins[k]
  stage.value = 'verify'
  allBin.value = ''
  listFilter.value = 'all'
  manualRoll.value = ''
  scanFlash.value = null
  lastHit.value = ''
  submitError.value = ''
  showConfirm.value = false
}

async function loadTransfer(scanned) {
  if (!scanned) return
  loadError.value = ''
  loadingTransfer.value = true
  try {
    const data = await getTransferForVerification(scanned)
    clearState()
    transfer.value = data
    restoreProgress(data.stock_entry, data.rolls.map(r => r.roll_no))
    if (route.query.se !== data.stock_entry) {
      router.replace({ query: { ...route.query, se: data.stock_entry } })
    }
  } catch (e) {
    loadError.value = e.message
  } finally {
    loadingTransfer.value = false
  }
}

function resetAll() {
  if (transfer.value && success.value) clearProgress(transfer.value.stock_entry)
  success.value = null
  transfer.value = null
  clearState()
  router.replace({ query: {} })
}

// ── Roll verification ───────────────────────────────────────────────────────
// Roll labels encode "item_code#reference#roll_no" (Create Rolls / Rolls
// pages); a bare roll number (typed, or an older label) also works.
function parseRollNo(text) {
  const t = String(text || '').trim()
  const parts = t.split('#')
  return (parts.length >= 3 ? parts[2] : t).trim()
}

let flashTimer = null
function flash(kind, msg) {
  scanFlash.value = { kind, msg }
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { scanFlash.value = null }, 3500)
}
function buzz(ok) { try { navigator.vibrate?.(ok ? 60 : [80, 60, 80]) } catch { /* unsupported */ } }

function verifyRoll(text) {
  if (!transfer.value) return
  const rollNo = parseRollNo(text)
  if (!rollNo) return
  const roll = rolls.value.find(r => r.roll_no === rollNo)
  if (!roll) {
    buzz(false)
    flash('err', `Roll ${rollNo} is not part of ${transfer.value.stock_entry}`)
    return
  }
  if (verified[rollNo]) {
    flash('warn', `Roll ${rollNo} is already verified`)
    return
  }
  verified[rollNo] = true
  lastHit.value = rollNo
  buzz(true)
  flash('ok', `Roll ${rollNo} verified · ${weightText(roll)}`)
}

function onManualRoll() {
  verifyRoll(manualRoll.value)
  manualRoll.value = ''
}

// Prompt once, the moment the last roll is verified
watch(allVerified, (now, before) => {
  if (now && !before && stage.value === 'verify') {
    if (scanner.open) closeScanner()
    if (transfer.value?.already_put_away) stage.value = 'done'
    else showConfirm.value = true
  }
})

function answer(yes) {
  showConfirm.value = false
  if (yes) goToBins()
  else stage.value = 'done'
}
function goToBins() {
  stage.value = 'bins'
  submitError.value = ''
}

// ── Bins ────────────────────────────────────────────────────────────────────
function binFetcher(nearWarehouse) {
  return async (txt) => {
    const rows = await searchBins(txt, nearWarehouse, transfer.value?.company)
    return rows.map(w => ({
      value: w.name,
      label: w.name,
      sub: w.parent_warehouse ? `in ${w.parent_warehouse}` : '',
    }))
  }
}
function applyAllBin() {
  if (!allBin.value) return
  for (const r of rolls.value) bins[r.roll_no] = allBin.value
}
// A scanned bin label must be an exact, usable warehouse name
async function resolveBin(text) {
  const t = String(text || '').trim()
  const rows = await searchBins(t, null, transfer.value?.company)
  const hit = rows.find(w => w.name === t) || rows.find(w => w.name.toLowerCase() === t.toLowerCase())
  if (!hit) throw new Error(`"${t}" is not a bin (leaf warehouse) in ${transfer.value?.company || 'this company'}`)
  return hit.name
}

// ── Stock Entry list for the picker ─────────────────────────────────────────
async function fetchTransfers(txt) {
  const rows = await searchMaterialTransfers(txt)
  return rows.map(s => ({
    value: s.name,
    label: s.name,
    sub: [s.posting_date, s.custom_roll_wise_pick_list, s.to_warehouse].filter(Boolean).join(' · '),
  }))
}

// ── Camera scanner (shared by Stock Entry / roll / bin scans) ──────────────
const scanner = reactive({ open: false, mode: '', rollNo: '', error: '' })
const scannerTitle = computed(() => ({
  se: 'Scan Stock Entry 2D Barcode',
  roll: 'Scan Roll Labels',
  bin: `Scan Bin for Roll ${scanner.rollNo}`,
  'bin-all': 'Scan Bin for All Rolls',
}[scanner.mode] || 'Scan'))
let html5QrCode = null
let lastText = ''
let lastAt = 0

async function openScanner(mode, rollNo = '') {
  Object.assign(scanner, { open: true, mode, rollNo, error: '' })
  await nextTick()
  try {
    html5QrCode = new Html5Qrcode('verify-camera-region')
    await html5QrCode.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
      onScan,
      () => {} // per-frame misses are normal
    )
  } catch (err) {
    scanner.error = 'Could not access the camera: ' + (err?.message || err)
  }
}
async function stopScanner() {
  if (!html5QrCode) return
  try {
    if (html5QrCode.isScanning) await html5QrCode.stop()
    html5QrCode.clear()
  } catch (err) { console.warn('Failed to stop camera scanner:', err) }
  html5QrCode = null
}
async function closeScanner() {
  await stopScanner()
  scanner.open = false
  scanner.error = ''
}

async function onScan(text) {
  // Rolls: keep the camera running for continuous scanning; ignore the same
  // label re-read while it's still in frame.
  if (scanner.mode === 'roll') {
    const now = Date.now()
    if (text === lastText && now - lastAt < 2500) return
    lastText = text; lastAt = now
    verifyRoll(text)
    return
  }

  const mode = scanner.mode
  const rollNo = scanner.rollNo
  await closeScanner()
  if (mode === 'se') {
    await loadTransfer(text)
  } else if (mode === 'bin' || mode === 'bin-all') {
    try {
      const wh = await resolveBin(text)
      if (mode === 'bin') bins[rollNo] = wh
      else { allBin.value = wh; applyAllBin() }
    } catch (e) {
      submitError.value = e.message
    }
  }
}

// ── Submit ──────────────────────────────────────────────────────────────────
async function submit(doSubmit) {
  submitError.value = ''
  submittingDraft.value = !doSubmit
  submitting.value = true
  try {
    const payload = rolls.value.map(r => ({ roll_no: r.roll_no, bin: bins[r.roll_no] }))
    success.value = await createVerifiedTransfer(transfer.value.stock_entry, payload, postingDate.value, doSubmit)
    clearProgress(transfer.value.stock_entry)
  } catch (e) {
    submitError.value = e.message
  } finally {
    submitting.value = false
  }
}

// ── Lifecycle ───────────────────────────────────────────────────────────────
onMounted(() => {
  if (route.query.se) loadTransfer(String(route.query.se))
})
onBeforeUnmount(() => {
  stopScanner()
  clearTimeout(flashTimer)
})
</script>

<style scoped>
.page-content { padding: 16px; max-width: 680px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 0; }

.form-label { display: block; font-size: 12px; font-weight: 700; text-transform: uppercase; color: #64748b; margin-bottom: 8px; }
.req { color: #dc2626; }
.form-input { width: 100%; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; font-size: 14px; box-sizing: border-box; }

.se-row { display: flex; gap: 8px; align-items: stretch; }
.se-select { flex: 1; min-width: 0; }

.btn { border: none; border-radius: 10px; cursor: pointer; font-size: 14px; font-weight: 600; padding: 11px 16px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-primary { background: var(--app-primary, #1e3a5f); color: #fff; }
.btn-outline { background: #fff; border: 1.5px solid var(--app-primary, #1e3a5f); color: var(--app-primary, #1e3a5f); }
.btn-icon { width: 44px; padding: 0; flex-shrink: 0; font-size: 18px; }
.btn-apply { flex-shrink: 0; }
.btn-full { width: 100%; }
.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; min-width: 0; }
.btn-ghost-link { background: none; color: #64748b; font-weight: 500; font-size: 13px; width: 100%; margin-top: 8px; }
.scan-row { margin-bottom: 10px; }
.btn-scan { width: 100%; min-height: 50px; font-size: 15px; }

.hint-text { font-size: 12px; color: #64748b; margin-top: 8px; display: flex; gap: 6px; align-items: flex-start; }
.hint-text span { flex: 1; line-height: 1.5; }

.error-banner { background: #fee2e2; color: #991b1b; padding: 10px; border-radius: 8px; display: flex; gap: 6px; align-items: center; justify-content: center; font-size: 13px; text-align: center; }
.warn-banner { background: #fef3c7; color: #92400e; padding: 10px; border-radius: 8px; display: flex; gap: 8px; font-size: 13px; margin-top: 12px; line-height: 1.45; }

.sum-title { font-size: 17px; font-weight: 800; color: #0f172a; overflow-wrap: anywhere; }
.sum-sub { font-size: 13px; color: #475569; margin-top: 2px; }
.wh-row { display: flex; gap: 6px; align-items: center; font-size: 13px; color: #334155; margin-top: 8px; overflow-wrap: anywhere; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }
.stat { background: #f8fafc; border-radius: 10px; padding: 10px 12px; }
.stat--ok { background: #f0fdf4; }
.stat__val { font-size: 22px; font-weight: 800; color: #0f172a; }
.stat__val span { font-size: 14px; font-weight: 600; color: #94a3b8; }
.stat--ok .stat__val { color: #15803d; }
.stat__lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #64748b; font-weight: 700; margin-top: 2px; }
.progress { height: 6px; background: #e2e8f0; border-radius: 6px; overflow: hidden; margin-top: 12px; }
.progress__bar { height: 100%; background: #16a34a; transition: width .3s; }

.flash { margin-top: 10px; padding: 10px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; display: flex; gap: 8px; align-items: center; }
.flash--ok { background: #dcfce7; color: #166534; }
.flash--warn { background: #fef3c7; color: #92400e; }
.flash--err { background: #fee2e2; color: #991b1b; }

.section-title { font-size: 14px; font-weight: 700; color: #0f172a; margin: 0 0 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.filter-tabs { display: inline-flex; background: #f1f5f9; border-radius: 8px; padding: 2px; }
.filter-tabs button { border: none; background: none; font-size: 12px; padding: 5px 10px; border-radius: 6px; color: #64748b; cursor: pointer; font-weight: 600; }
.filter-tabs button.on { background: #fff; color: #0f172a; box-shadow: 0 1px 2px rgba(0,0,0,.08); }

.roll-list { display: flex; flex-direction: column; gap: 8px; }
.roll { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; transition: background .3s, border-color .3s; }
.roll--ok { border-color: #bbf7d0; background: #f7fef9; }
.roll--hit { box-shadow: 0 0 0 2px #22c55e; }
.roll__head { display: flex; gap: 10px; }
.roll__main { flex: 1; min-width: 0; }
.roll__no { font-weight: 800; font-size: 14px; color: #0f172a; }
.roll__meta { font-size: 12px; color: #64748b; overflow-wrap: anywhere; }
.roll__right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
.roll__wt { font-size: 14px; font-weight: 800; color: #0f172a; white-space: nowrap; }
.badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 20px; white-space: nowrap; }
.badge--ok { background: #dcfce7; color: #15803d; }
.badge--pending { background: #f1f5f9; color: #64748b; }
.roll__bin { margin-top: 10px; padding-top: 10px; border-top: 1px dashed #e2e8f0; }
.roll__from { font-size: 12px; color: #475569; margin-bottom: 6px; overflow-wrap: anywhere; }
.mini-err { font-size: 12px; color: #dc2626; margin-top: 4px; }
.empty { text-align: center; color: #94a3b8; font-size: 13px; padding: 14px; }

.done-card { text-align: center; }
.done-card__icon { font-size: 40px; color: #16a34a; }
.done-card__title { font-size: 17px; font-weight: 800; margin-top: 6px; }
.done-card__sub { font-size: 13px; color: #64748b; margin: 4px 0 14px; }

/* Modals */
.modal-overlay { position: fixed; inset: 0; background: rgba(15,23,42,.55); display: flex; align-items: center; justify-content: center; z-index: 500; padding: 20px; }
.modal-box { background: #fff; border-radius: 14px; padding: 24px 20px; width: 100%; max-width: 380px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,.25); }
.scanner-box { max-width: 420px; }
.camera-region { width: 100%; aspect-ratio: 1/1; border-radius: 10px; overflow: hidden; background: #0f172a; }
.camera-region :deep(video) { width: 100% !important; height: 100% !important; object-fit: cover !important; }
.scanner-count { margin-top: 10px; font-weight: 800; font-size: 15px; color: #0f172a; }
.modal-icon { font-size: 40px; color: #16a34a; display: block; margin-bottom: 8px; }
.modal-title { font-size: 17px; font-weight: 700; margin: 0 0 8px; color: #0f172a; }
.modal-msg { font-size: 13.5px; color: #475569; margin: 0 0 16px; line-height: 1.5; }
.modal-docno { font-size: 15px; font-weight: 700; color: var(--app-primary, #1e3a5f); background: #f1f5f9; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; word-break: break-all; }
.modal-fade-enter-active, .modal-fade-leave-active { transition: opacity .2s; }
.modal-fade-enter-from, .modal-fade-leave-to { opacity: 0; }
</style>
