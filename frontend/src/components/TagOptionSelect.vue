<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

type Option = { value: string; label: string; color?: string }
const props = defineProps<{
  label: string
  modelValue: string
  options: Option[]
  placeholder?: string
  searchable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [value: string] }>()

const trigger = ref<HTMLButtonElement | null>(null)
const popup = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const optionList = ref<HTMLElement | null>(null)
const open = ref(false)
const query = ref('')
const activeIndex = ref(0)
const placement = ref({ top: 0, left: 0, width: 0, maxHeight: 280 })
const popupTheme = ref<Record<string,string>>({})
const selected = computed(() => props.options.find(option => option.value === props.modelValue))
const visibleOptions = computed(() => props.options.filter(option =>
  option.label.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()),
))
const rowHeight = 38
const windowSize = 12
const startIndex = ref(0)
const renderedOptions = computed(() => visibleOptions.value.slice(startIndex.value, startIndex.value + windowSize))
watch(query, () => { startIndex.value = 0; if (optionList.value) optionList.value.scrollTop = 0; activeIndex.value = 0 })
function scrollOptions() { startIndex.value = Math.max(0, Math.floor((optionList.value?.scrollTop || 0) / rowHeight) - 2) }
function revealActive() {
  const list = optionList.value
  if (!list) return
  const top = activeIndex.value * rowHeight
  if (top < list.scrollTop) list.scrollTop = top
  else if (top + rowHeight > list.scrollTop + list.clientHeight) list.scrollTop = top + rowHeight - list.clientHeight
  scrollOptions()
}

function positionPopup() {
  if (!trigger.value || !open.value) return
  const rect = trigger.value.getBoundingClientRect()
  const source = getComputedStyle(trigger.value)
  popupTheme.value = Object.fromEntries(['--panel','--line','--ink','--muted','--accent','--accent-soft'].map(key => [key, source.getPropertyValue(key).trim()]))
  const below = window.innerHeight - rect.bottom - 12
  const above = rect.top - 12
  const height = Math.min(280, Math.max(100, visibleOptions.value.length * 39 + (props.searchable ? 56 : 12)))
  const flip = below < height && above > below
  placement.value = {
    top: flip ? Math.max(8, rect.top - Math.min(height, above) - 5) : rect.bottom + 5,
    left: Math.max(8, Math.min(rect.left, window.innerWidth - rect.width - 8)),
    width: rect.width,
    maxHeight: Math.max(80, Math.min(280, flip ? above : below)),
  }
}

async function show() {
  open.value = true
  query.value = ''
  activeIndex.value = Math.max(0, props.options.findIndex(option => option.value === props.modelValue))
  await nextTick()
  positionPopup()
  revealActive()
  if (props.searchable) searchInput.value?.focus({ preventScroll: true })
}
function hide(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus({ preventScroll: true })
}
function choose(option: Option) {
  emit('update:modelValue', option.value)
  emit('change', option.value)
  hide(true)
}
function onOutside(event: PointerEvent) {
  const target = event.target as Node
  if (open.value && !trigger.value?.contains(target) && !popup.value?.contains(target)) hide()
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); hide(true); return }
  if (event.key === 'Tab') { event.preventDefault(); event.stopPropagation(); hide(true); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (visibleOptions.value.length) { activeIndex.value = (activeIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + visibleOptions.value.length) % visibleOptions.value.length; revealActive() }
  }
  if (event.key === 'Enter' && visibleOptions.value[activeIndex.value]) {
    event.preventDefault()
    choose(visibleOptions.value[activeIndex.value])
  }
}

document.addEventListener('pointerdown', onOutside)
window.addEventListener('resize', positionPopup)
window.addEventListener('scroll', positionPopup, true)
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutside)
  window.removeEventListener('resize', positionPopup)
  window.removeEventListener('scroll', positionPopup, true)
})
</script>

<template>
  <div class="tag-option-select">
    <button ref="trigger" type="button" class="tag-option-trigger" :aria-label="label" :aria-expanded="open" aria-haspopup="listbox" @click="open ? hide() : show()" @keydown.down.prevent="show()" @keydown.esc.stop.prevent="hide()">
      <span v-if="selected?.color" class="tag-option-dot" :style="{ background: selected.color }" />
      <span :class="{placeholder:!selected}">{{selected?.label || placeholder || '请选择'}}</span>
      <span class="tag-option-chevron">⌄</span>
    </button>
    <Teleport to="body">
      <div v-if="open" ref="popup" class="tag-option-popup" role="listbox" :aria-label="label" :style="{...popupTheme,top:`${placement.top}px`,left:`${placement.left}px`,width:`${placement.width}px`,maxHeight:`${placement.maxHeight}px`}" @keydown="onKeydown">
        <input v-if="searchable" ref="searchInput" v-model="query" :aria-label="`搜索${label}`" :placeholder="`搜索${label}`" @input="activeIndex=0" />
        <div ref="optionList" class="tag-option-list" @scroll="scrollOptions">
          <div :style="{height:`${startIndex * rowHeight}px`}" aria-hidden="true" />
          <button v-for="(option,index) in renderedOptions" :key="option.value" type="button" role="option" :aria-selected="option.value===modelValue" :class="{active:startIndex+index===activeIndex,selected:option.value===modelValue}" @click="choose(option)" @mouseenter="activeIndex=startIndex+index">
            <span v-if="option.color" class="tag-option-dot" :style="{background:option.color}" />
            <span>{{option.label}}</span><b v-if="option.value===modelValue">✓</b>
          </button>
          <div :style="{height:`${Math.max(0,visibleOptions.length-startIndex-renderedOptions.length) * rowHeight}px`}" aria-hidden="true" />
          <p v-if="!visibleOptions.length">没有匹配的选项</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style>
.tag-option-select{min-width:0}.tag-option-trigger{display:flex;align-items:center;gap:9px;width:100%;height:40px;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font-size:14px;text-align:left;cursor:pointer}.tag-option-trigger:hover,.tag-option-trigger[aria-expanded=true]{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}.tag-option-trigger>span:nth-last-child(2){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tag-option-trigger .placeholder{color:var(--muted)}.tag-option-chevron{margin-left:auto;color:var(--muted)}.tag-option-dot{display:inline-block;flex:0 0 12px;width:12px;height:12px;border-radius:50%}.tag-option-popup{position:fixed;z-index:200;overflow:auto;padding:7px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);box-shadow:0 15px 35px #0004}.tag-option-popup>input{width:100%;min-height:34px;padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);font-size:13px;outline:0}.tag-option-popup>input:focus{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}.tag-option-list{overflow:auto;max-height:205px;padding-top:4px}.tag-option-list button{display:flex;align-items:center;gap:9px;width:100%;height:38px;min-height:38px;padding:8px;border:0;border-radius:7px;background:transparent;color:var(--ink);font-size:13px;text-align:left;cursor:pointer}.tag-option-list button:hover,.tag-option-list button.active,.tag-option-list button.selected{background:var(--accent-soft)}.tag-option-list button b{margin-left:auto;color:var(--accent)}.tag-option-list p{margin:8px;color:var(--muted);font-size:12px}
</style>
