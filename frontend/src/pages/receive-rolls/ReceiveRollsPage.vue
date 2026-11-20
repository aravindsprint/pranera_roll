<template>
  <div class="page">
    <AppHeader title="Receive Rolls" active="receive-rolls" :username="auth.username" :designation="auth.designation" />
    <div class="page-content">

      <!-- ── 1. Pick the draft receipt ───────────────────────────────────── -->
      <div class="card">
        <div class="rr-type">
          <button v-for="t in TYPES" :key="t.value" class="rr-type__btn" :class="{ 'rr-type__btn--on': doctype === t.value }"
                  :disabled="saving" @click="setType(t.value)">{{ t.label }}</button>
        </div>
        <label class="form-label">Draft {{ doctype }} <span class="req">*</span></label>
        <RemoteSelect
          :model-value="receipt?.name || ''"
          :fetcher="fetchReceipts"
          :disabled="loading || saving"
          placeholder="Search receipt no / supplier…"
          @change="opt => opt && load(opt.value)"
          @enter="load"
        />
        <div v-if="loading" class="hint-text"><i class="pi pi-spin pi-spinner"></i><span>Loading…</span></div>
        <div v-if="loadError" class="error-banner" style="margin-top:10px"><i class="pi pi-exclamation-triangle"></i> {{ loadError }}</div>
      </div>

      <template v-if="receipt && !done">
        <div class="card">
          <div class="rr-sum-title">{{ receipt.name }}</div>
          <div class="rr-sum-sub">
            {{ receipt.supplier_name || receipt.supplier }}<span v-if="receipt.posting_date"> · {{ receipt.posting_date }}</span>
            · tolerance {{ receipt.tolerance_percent }}%
          </div>
          <div v-if="receipt.packing_list" class="hint-text"><i class="pi pi-info-circle"></i>
            <span>Already received on {{ receipt.packing_list }} — edit below and save again to replace it. Roll numbers are kept.</span>
          </div>
        </div>

        <!-- ── 2. One card per item: add rolls ──────────────────────────── -->
        <div v-for="it in receipt.items" :key="it.item_code" class="card">
          <div class="rr-item-head">
            <div>
              <div class="rr-item-code">{{ it.item_code }}</div>
              <div class="rr-item-sub">{{ it.item_name }} → {{ it.warehouse }}</div>
            </div>
            <div class="rr-total" :class="totals(it).ok ? 'rr-total--ok' : 'rr-total--off'">
              <div class="rr-total__val">{{ fmt(totals(it).got) }}<span>/{{ fmt(it.qty) }} {{ it.is_kg ? 'kg' : 'pcs' }}</span></div>
              <div class="rr-total__lbl">{{ rolls[it.item_code].length }} rolls<span v-if="!it.is_kg"> · {{ fmt(totals(it).kg) }} kg</span></div>
            </div>
          </div>
          <div class="progress"><div class="progress__bar" :style="{ width: pct(it) + '%' }"></div></div>

          <div class="rr-add">
            <input :ref="el => (weightInputs[it.item_code] = el)" v-model="draft[it.item_code].w" class="form-input" type="number"
                   inputmode="decimal" step="0.001" min="0" placeholder="Weight kg" :disabled="saving"
                   @keydown.enter.prevent="it.is_kg ? addRoll(it) : focusPcs(it)" />
            <input v-if="!it.is_kg" :ref="el => (pcsInputs[it.item_code] = el)" v-model="draft[it.item_code].p" class="form-input"
                   type="number" inputmode="numeric" step="1" min="0" placeholder="Pcs" :disabled="saving"
                   @keydown.enter.prevent="addRoll(it)" />
            <button class="btn btn-primary" :disabled="saving" @click="addRoll(it)"><i class="pi pi-plus"></i></button>
          </div>

          <div class="rr-list">
            <div v-for="(r, j) in rolls[it.item_code]" :key="j" class="rr-roll">
              <span class="rr-roll__no">{{ j + 1 }}. {{ r.roll_no || 'new' }}</span>
              <input v-model.number="r.roll_weight" class="form-input rr-roll__in" type="number" inputmode="decimal" step="0.001" :disabled="saving" />
              <span class="rr-roll__unit">kg</span>
              <template v-if="!it.is_kg">
                <input v-model.number="r.total_qty" class="form-input rr-roll__in" type="number" inputmode="numeric" step="1" :disabled="saving" />
                <span class="rr-roll__unit">pcs</span>
              </template>
              <button class="btn btn-outline rr-roll__del" :disabled="saving" @click="rolls[it.item_code].splice(j, 1)"><i class="pi pi-times"></i></button>
            </div>
            <div v-if="!rolls[it.item_code].length" class="hint-text">No rolls yet — enter each roll's weight and press Enter.</div>
          </div>
        </div>

        <div class="card">
          <div v-if="saveError" class="error-banner" style="margin-bottom:10px"><i class="pi pi-exclamation-triangle"></i> {{ saveError }}</div>
          <button class="btn btn-primary btn-full" :disabled="saving || !canSave" @click="save">
            <i class="pi" :class="saving ? 'pi-spin pi-spinner' : 'pi-check'"></i>
            <span>{{ saving ? 'Creating rolls…' : `Save ${rollCount} Rolls` }}</span>
          </button>
          <div v-if="!allOk && rollCount" class="hint-text" style="margin-top:8px"><i class="pi pi-info-circle"></i>
            <span>Totals must match each item's received qty (± {{ receipt.tolerance_percent }}%).</span>
          </div>
        </div>
      </template>

      <!-- ── 3. Done: print stickers ────────────────────────────────────── -->
      <div v-if="done" class="card done-card">
        <i class="pi pi-verified done-card__icon"></i>
        <div class="done-card__title">{{ done.rolls.length }} rolls received</div>
        <div class="done-card__sub">{{ receipt?.name }} · Packing List {{ done.packing_list }}</div>
        <div class="rr-done-list">
          <div v-for="r in done.rolls" :key="r.name" class="rr-done-row">
            <b>{{ r.name }}</b><span>{{ r.item_code }}</span><span>{{ fmt(r.roll_weight) }} kg<template v-if="r.total_qty"> · {{ r.total_qty }} pcs</template></span>
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" @click="printRollStickers(done.rolls)"><i class="pi pi-print"></i><span>Print {{ done.rolls.length }} Stickers</span></button>
          <button class="btn btn-outline" @click="reset">Receive Another</button>
        </div>
        <div class="hint-text" style="justify-content:center;margin-top:8px">Submit the receipt in ERP — the rolls get their batch on submit.</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AppHeader from '@/components/AppHeader.vue'
import RemoteSelect from '@/components/RemoteSelect.vue'
import { searchReceiptsForRolls, getReceiptForRolls, receiveRolls } from '@/api/frappe'
import { printRollStickers } from '@/utils/rollSticker'

const auth = useAuthStore()
const TYPES = [
  { value: 'Subcontracting Receipt', label: 'Subcontracting Receipt' },
  { value: 'Purchase Receipt', label: 'Purchase Receipt' },
]

const doctype = ref('Subcontracting Receipt')
const receipt = ref(null)
const rolls = reactive({})     // item_code -> [{ roll_no?, roll_weight, total_qty }]
const draft = reactive({})     // item_code -> { w, p }
const weightInputs = {}
const pcsInputs = {}
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')
const done = ref(null)

const fmt = n => (Math.round((Number(n) || 0) * 1000) / 1000).toLocaleString('en-IN', { maximumFractionDigits: 3 })

function totals(it) {
  const list = rolls[it.item_code] || []
  const kg = list.reduce((a, r) => a + (Number(r.roll_weight) || 0), 0)
  const pcs = list.reduce((a, r) => a + (Number(r.total_qty) || 0), 0)
  const got = it.is_kg ? kg : pcs
  const tol = Math.max(it.qty * (receipt.value?.tolerance_percent || 0) / 100, 0.001)
  return { kg, pcs, got, ok: Math.abs(got - it.qty) <= tol }
}
const pct = it => Math.min(100, (totals(it).got / (it.qty || 1)) * 100)
const rollCount = computed(() => Object.values(rolls).reduce((a, l) => a + l.length, 0))
const allOk = computed(() => !!receipt.value && receipt.value.items.every(it => totals(it).ok))
const canSave = computed(() => rollCount.value > 0 && allOk.value)

function setType(t) {
  if (doctype.value === t) return
  doctype.value = t
  reset()
}

async function fetchReceipts(txt) {
  const rows = await searchReceiptsForRolls(txt, doctype.value)
  return rows.map(r => ({
    value: r.name,
    label: r.name,
    sub: [r.supplier_name, r.posting_date, r.custom_roll_packing_list ? `received: ${r.custom_roll_packing_list}` : ''].filter(Boolean).join(' · '),
  }))
}

async function load(name) {
  name = (name || '').trim()
  if (!name) return
  loading.value = true; loadError.value = ''; done.value = null; saveError.value = ''
  try {
    const rc = await getReceiptForRolls(doctype.value, name)
    if (!rc.items.length) throw new Error(`${name} has no roll items`)
    Object.keys(rolls).forEach(k => delete rolls[k])
    Object.keys(draft).forEach(k => delete draft[k])
    rc.items.forEach(it => { rolls[it.item_code] = []; draft[it.item_code] = { w: '', p: '' } })
    rc.rolls.forEach(r => rolls[r.item_code]?.push({ roll_no: r.roll_no, roll_weight: r.roll_weight, total_qty: r.total_qty }))
    receipt.value = rc
    await nextTick()
    weightInputs[rc.items[0].item_code]?.focus()
  } catch (e) {
    receipt.value = null
    loadError.value = e.message || 'Could not load the receipt'
  } finally {
    loading.value = false
  }
}

function focusPcs(it) { pcsInputs[it.item_code]?.focus() }

function addRoll(it) {
  const d = draft[it.item_code]
  const w = Number(d.w), p = Number(d.p || 0)
  if (!(w > 0)) { weightInputs[it.item_code]?.focus(); return }
  if (!it.is_kg && !(p > 0)) { focusPcs(it); return }
  rolls[it.item_code].push({ roll_weight: Math.round(w * 1000) / 1000, total_qty: it.is_kg ? null : p })
  d.w = ''; d.p = ''
  weightInputs[it.item_code]?.focus()
}

async function save() {
  if (!canSave.value) return
  saving.value = true; saveError.value = ''
  try {
    const payload = []
    receipt.value.items.forEach(it => rolls[it.item_code].forEach(r => payload.push({ item_code: it.item_code, ...r })))
    const res = await receiveRolls(doctype.value, receipt.value.name, payload)
    done.value = res
  } catch (e) {
    saveError.value = e.message || 'Saving failed'
  } finally {
    saving.value = false
  }
}

function reset() {
  receipt.value = null; done.value = null; loadError.value = ''; saveError.value = ''
  Object.keys(rolls).forEach(k => delete rolls[k])
  Object.keys(draft).forEach(k => delete draft[k])
}
</script>

<style scoped>
/* shared bits (same as Verify Rolls; those are scoped per page in this app) */
.req { color: #dc2626; }
.btn-row { display: flex; gap: 10px; }
.btn-row .btn { flex: 1; min-width: 0; }
.hint-text { font-size: 12px; color: #64748b; margin-top: 8px; display: flex; gap: 6px; align-items: flex-start; }
.hint-text span { flex: 1; line-height: 1.5; }
.error-banner { background: #fee2e2; color: #991b1b; padding: 10px; border-radius: 8px; display: flex; gap: 6px; align-items: center; justify-content: center; font-size: 13px; text-align: center; }
.done-card { text-align: center; }
.done-card__icon { font-size: 40px; color: #16a34a; }
.done-card__title { font-size: 17px; font-weight: 800; margin-top: 6px; }
.done-card__sub { font-size: 13px; color: #64748b; margin: 4px 0 4px; }

.rr-type { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }
.rr-type__btn {
  padding:10px 6px; border:2px solid var(--slate-200,#e2e8f0); border-radius:12px; background:white;
  font-family:inherit; font-size:12.5px; font-weight:700; color:var(--slate-700,#334155); cursor:pointer;
}
.rr-type__btn--on { border-color:var(--app-primary,#0f6e56); background:rgba(15,110,86,0.08); color:var(--app-primary,#0f6e56); }

.rr-sum-title { font-size:16px; font-weight:800; color:var(--slate-900,#0f172a); }
.rr-sum-sub { font-size:12px; color:var(--slate-500,#64748b); margin:2px 0 6px; }

.rr-item-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.rr-item-code { font-size:14px; font-weight:800; color:var(--slate-900,#0f172a); word-break:break-word; }
.rr-item-sub { font-size:11.5px; color:var(--slate-500,#64748b); margin-top:2px; }
.rr-total { text-align:right; flex-shrink:0; }
.rr-total__val { font-size:17px; font-weight:900; }
.rr-total__val span { font-size:12px; font-weight:600; color:var(--slate-400,#94a3b8); }
.rr-total__lbl { font-size:11px; color:var(--slate-500,#64748b); }
.rr-total--ok .rr-total__val { color:var(--app-primary,#0f6e56); }
.rr-total--off .rr-total__val { color:#c2410c; }

.progress { height:6px; background:var(--slate-100,#f1f5f9); border-radius:4px; overflow:hidden; margin:10px 0 12px; }
.progress__bar { height:100%; background:var(--app-primary,#0f6e56); transition:width .2s; }

.rr-add { display:flex; gap:8px; }
.rr-add .form-input { flex:1; min-width:0; font-size:16px; }
.rr-add .btn { flex-shrink:0; width:48px; }

.rr-list { margin-top:10px; display:flex; flex-direction:column; gap:6px; }
.rr-roll { display:flex; align-items:center; gap:6px; padding:6px 8px; border:1px solid var(--slate-100,#f1f5f9); border-radius:10px; }
.rr-roll__no { font-size:12px; font-weight:700; color:var(--slate-600,#475569); width:58px; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rr-roll__in { flex:1 1 0; min-width:0; max-width:96px; padding:6px 8px; font-size:14px; }
.rr-roll__unit { font-size:11px; color:var(--slate-400,#94a3b8); }
.rr-roll__del { margin-left:auto; padding:6px 9px; flex-shrink:0; }

.rr-done-list { margin:12px 0; text-align:left; max-height:280px; overflow-y:auto; }
.rr-done-row { display:flex; gap:10px; justify-content:space-between; font-size:12.5px; padding:6px 4px; border-bottom:1px solid var(--slate-100,#f1f5f9); }
.rr-done-row span { color:var(--slate-500,#64748b); }
</style>
