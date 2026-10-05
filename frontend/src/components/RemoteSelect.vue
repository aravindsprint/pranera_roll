<template>
  <div class="rs" ref="rootEl">
    <div class="rs-input-wrap">
      <input
        ref="inputEl"
        v-model="query"
        type="text"
        class="form-input rs-input"
        :placeholder="placeholder"
        :disabled="disabled"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        @focus="onFocus"
        @input="onInput"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="onEnter"
        @keydown.esc="close"
      />
      <button v-if="query && !disabled" type="button" class="rs-clear" tabindex="-1" @click="clear">
        <i class="pi pi-times"></i>
      </button>
      <i v-if="loading" class="pi pi-spin pi-spinner rs-icon"></i>
      <i v-else class="pi pi-search rs-icon"></i>
    </div>

    <div v-if="open" class="rs-panel">
      <div
        v-for="(opt, idx) in options"
        :key="opt.value"
        class="rs-option"
        :class="{ 'rs-option--active': idx === highlighted, 'rs-option--selected': opt.value === modelValue }"
        @mousedown.prevent="choose(opt)"
        @mousemove="highlighted = idx"
      >
        <div class="rs-option__label">{{ opt.label }}</div>
        <div v-if="opt.sub" class="rs-option__sub">{{ opt.sub }}</div>
      </div>
      <div v-if="!loading && !options.length" class="rs-empty">
        {{ error || `No matches${query ? ` for "${query}"` : ''}` }}
      </div>
    </div>
  </div>
</template>

<script setup>
// Server-side search select. Unlike AutoComplete.vue (which filters a list
// it already holds), this asks the server on every keystroke (debounced) —
// needed for Stock Entries and the site's 5000+ warehouses/bins.
//
// fetcher(txt) must resolve to [{ value, label, sub? }].
// Enter with no highlighted option submits the raw text via 'enter' —
// lets a keyboard-wedge barcode scanner type a value straight in.
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue:  { type: String, default: '' },
  fetcher:     { type: Function, required: true },
  placeholder: { type: String, default: 'Search...' },
  disabled:    { type: Boolean, default: false },
  debounceMs:  { type: Number, default: 250 },
})
const emit = defineEmits(['update:modelValue', 'change', 'enter'])

const rootEl = ref(null)
const inputEl = ref(null)
const query = ref(props.modelValue || '')
const options = ref([])
const open = ref(false)
const loading = ref(false)
const error = ref('')
const highlighted = ref(-1)
let timer = null
let seq = 0

watch(() => props.modelValue, v => { if (!open.value) query.value = v || '' })

async function load(txt) {
  const mySeq = ++seq
  loading.value = true
  error.value = ''
  try {
    const rows = await props.fetcher(txt || '')
    if (mySeq !== seq) return            // a newer request superseded this one
    options.value = rows || []
    highlighted.value = options.value.length ? 0 : -1
  } catch (e) {
    if (mySeq !== seq) return
    options.value = []
    error.value = e.message || 'Search failed'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

function onFocus() {
  open.value = true
  // Selected value shown in the box → search from scratch, not for itself
  load(query.value === props.modelValue ? '' : query.value)
}
function onInput() {
  open.value = true
  clearTimeout(timer)
  timer = setTimeout(() => load(query.value), props.debounceMs)
}
function move(step) {
  if (!open.value) { open.value = true; return }
  const n = options.value.length
  if (!n) return
  highlighted.value = (highlighted.value + step + n) % n
}
function onEnter() {
  if (open.value && highlighted.value >= 0 && options.value[highlighted.value] && !loading.value) {
    choose(options.value[highlighted.value])
  } else if (query.value.trim()) {
    emit('enter', query.value.trim())
    close()
  }
}
function choose(opt) {
  query.value = opt.value
  emit('update:modelValue', opt.value)
  emit('change', opt)
  close()
  inputEl.value?.blur()
}
function clear() {
  query.value = ''
  emit('update:modelValue', '')
  emit('change', null)
  inputEl.value?.focus()
}
function close() {
  open.value = false
  if (!query.value) return
  // Typed but not chosen → snap back to the real selection
  if (query.value !== props.modelValue) query.value = props.modelValue || ''
}
function onDocClick(e) { if (rootEl.value && !rootEl.value.contains(e.target)) close() }

onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => { document.removeEventListener('mousedown', onDocClick); clearTimeout(timer) })

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<style scoped>
.rs { position: relative; width: 100%; }
.rs-input-wrap { position: relative; }
.rs-input {
  width: 100%; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 58px 10px 12px;
  font-size: 14px; box-sizing: border-box; background: #fff;
}
.rs-input:focus { outline: none; border-color: var(--app-primary, #1e3a5f); box-shadow: 0 0 0 3px rgba(30,58,95,0.12); }
.rs-icon { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: #94a3b8; font-size: 13px; pointer-events: none; }
.rs-clear {
  position: absolute; right: 32px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: #94a3b8; cursor: pointer; padding: 4px; font-size: 12px;
}
.rs-panel {
  position: absolute; z-index: 400; left: 0; right: 0; top: calc(100% + 4px);
  background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12); max-height: 280px; overflow-y: auto;
}
.rs-option { padding: 9px 12px; cursor: pointer; border-bottom: 1px solid #f1f5f9; }
.rs-option:last-child { border-bottom: none; }
.rs-option--active { background: #f1f5f9; }
.rs-option--selected .rs-option__label { color: var(--app-primary, #1e3a5f); font-weight: 700; }
.rs-option__label { font-size: 14px; color: #0f172a; overflow-wrap: anywhere; }
.rs-option__sub { font-size: 11.5px; color: #64748b; margin-top: 2px; overflow-wrap: anywhere; }
.rs-empty { padding: 12px; font-size: 13px; color: #94a3b8; text-align: center; }
</style>
