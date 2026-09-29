import { nextTick, onBeforeUnmount, onMounted, watch, type ComputedRef } from 'vue'

const DIALOG_SELECTOR = '.modal-stage > section, .detail-sheet-stage > section, .detail-sheet-stage > aside, .login-stage > section, .media-viewer'
const FOCUS_SELECTOR = 'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

export function useDialogAccessibility(openCount: ComputedRef<number>, closeTop: () => void) {
  let returnTarget: HTMLElement | null = null

  function visibleDialogs() {
    return [...document.querySelectorAll<HTMLElement>(DIALOG_SELECTOR)].filter(item => item.offsetParent !== null)
  }

  function prepareTopDialog() {
    const dialog = visibleDialogs().at(-1)
    if (!dialog) return
    dialog.setAttribute('role', 'dialog')
    dialog.setAttribute('aria-modal', 'true')
    if (!dialog.hasAttribute('aria-label') && !dialog.hasAttribute('aria-labelledby')) {
      dialog.setAttribute('aria-label', dialog.querySelector('h2')?.textContent?.trim() || '对话框')
    }
    if (!dialog.hasAttribute('tabindex')) dialog.tabIndex = -1
    const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUS_SELECTOR)]
    const preferred = dialog.querySelector<HTMLElement>('[autofocus]') || focusable.find(item => !item.classList.contains('close')) || focusable[0]
    ;(preferred || dialog).focus({ preventScroll: true })
  }

  function onKeydown(event: KeyboardEvent) {
    if (!openCount.value) return
    const dialog = visibleDialogs().at(-1)
    if (!dialog) return
    if (event.key === 'Escape') {
      event.preventDefault()
      closeTop()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUS_SELECTOR)].filter(item => item.offsetParent !== null)
    if (!focusable.length) {
      event.preventDefault()
      dialog.focus()
      return
    }
    const first = focusable[0]
    const last = focusable.at(-1)!
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus()
    }
  }

  watch(openCount, async (count, previous) => {
    if (count > 0 && previous === 0) returnTarget = document.activeElement as HTMLElement | null
    if (count > 0) { await nextTick(); prepareTopDialog() }
    if (count === 0 && previous > 0) {
      await nextTick()
      if (returnTarget?.isConnected) returnTarget.focus({ preventScroll: true })
      returnTarget = null
    }
  })
  onMounted(() => document.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
}
