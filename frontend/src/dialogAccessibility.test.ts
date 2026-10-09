// @vitest-environment happy-dom
import { computed, createApp, h, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { detailNavigationDirection, isElementVisible, prepareDialog, trapDialogTab, useDialogAccessibility } from './dialogAccessibility'

describe('dialog accessibility helpers', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('adds dialog semantics and focuses the first useful control', () => {
    const dialog = document.createElement('section')
    dialog.innerHTML = '<h2>编辑素材</h2><button class="close">关闭</button><input />'
    document.body.append(dialog)
    prepareDialog(dialog)
    expect(dialog.getAttribute('role')).toBe('dialog')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.getAttribute('aria-label')).toBe('编辑素材')
    expect(document.activeElement).toBe(dialog.querySelector('input'))
  })

  it('keeps focus inside an empty dialog', () => {
    const dialog = document.createElement('section')
    document.body.append(dialog)
    const event = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true })
    trapDialogTab(dialog, event)
    expect(event.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(dialog)
  })

  it('cycles focus between the first and last controls', () => {
    const dialog = document.createElement('section')
    dialog.innerHTML = '<button id="first">第一个</button><button id="last">最后一个</button>'
    document.body.append(dialog)
    for (const button of dialog.querySelectorAll('button')) {
      Object.defineProperty(button, 'offsetParent', { value: dialog })
    }
    const first = dialog.querySelector<HTMLElement>('#first')!
    const last = dialog.querySelector<HTMLElement>('#last')!
    last.focus()
    const forward = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true })
    trapDialogTab(dialog, forward)
    expect(forward.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(first)
    const backward = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true })
    trapDialogTab(dialog, backward)
    expect(backward.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(last)
  })

  it('maps arrow keys only when focus is not editing a field', () => {
    const stage = document.createElement('div')
    stage.className = 'detail-sheet-stage'
    const dialog = document.createElement('aside')
    const input = document.createElement('input')
    dialog.append(input)
    stage.append(dialog)
    document.body.append(stage)
    expect(detailNavigationDirection(new KeyboardEvent('keydown', { key: 'ArrowLeft' }), dialog)).toBe(-1)
    expect(detailNavigationDirection(new KeyboardEvent('keydown', { key: 'ArrowRight' }), dialog)).toBe(1)
    expect(detailNavigationDirection(new KeyboardEvent('keydown', { key: 'ArrowRight', ctrlKey: true }), dialog)).toBeNull()
    const editingEvent = new KeyboardEvent('keydown', { key: 'ArrowLeft' })
    Object.defineProperty(editingEvent, 'target', { value: input })
    expect(detailNavigationDirection(editingEvent, dialog)).toBeNull()
  })

  it('recognizes a fixed detail sheet and handles its arrow keys', async () => {
    const navigate = vi.fn(() => true)
    const app = createApp({
      setup() {
        useDialogAccessibility(computed(() => 1), vi.fn(), navigate)
        return () => h('div', { class: 'detail-sheet-stage' }, [
          h('aside', { class: 'detail-sheet', style: 'position:fixed' }, [h('button', '上一项')]),
        ])
      },
    })
    const host = document.createElement('div')
    document.body.append(host)
    app.mount(host)
    await nextTick()
    const dialog = document.querySelector<HTMLElement>('.detail-sheet')!
    Object.defineProperty(dialog, 'offsetParent', { value: null })
    expect(dialog.offsetParent).toBeNull()
    expect(isElementVisible(dialog)).toBe(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true }))
    expect(navigate).toHaveBeenCalledWith(1)
    app.unmount()
  })

  it('handles Escape and restores focus after the dialog closes', async () => {
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
      configurable: true,
      get(this: HTMLElement) { return this.parentElement },
    })
    const openCount = ref(0)
    const closeTop = vi.fn(() => { openCount.value = 0 })
    const app = createApp({
      setup() {
        useDialogAccessibility(computed(() => openCount.value), closeTop)
        return () => h('div', [
          h('button', { id: 'trigger' }, '打开'),
          openCount.value ? h('div', { class: 'modal-stage' }, [
            h('section', [h('h2', '筛选'), h('button', { autofocus: true }, '确定')]),
          ]) : null,
        ])
      },
    })
    const host = document.createElement('div')
    document.body.append(host)
    app.mount(host)
    const trigger = document.querySelector<HTMLElement>('#trigger')!
    trigger.focus()
    openCount.value = 1
    await nextTick()
    await nextTick()
    expect(document.activeElement?.textContent).toBe('确定')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    await nextTick()
    await nextTick()
    expect(closeTop).toHaveBeenCalledOnce()
    expect(document.activeElement).toBe(trigger)
    app.unmount()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(closeTop).toHaveBeenCalledOnce()
    delete (HTMLElement.prototype as HTMLElement & { offsetParent?: Element }).offsetParent
  })
})
