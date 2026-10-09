import { nextTick, onBeforeUnmount, onMounted, watch, type ComputedRef } from 'vue'

const DIALOG_SELECTOR = '.modal-stage > section, .detail-sheet-stage > section, .detail-sheet-stage > aside, .login-stage > section, .media-viewer'
const FOCUS_SELECTOR = 'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

export function isElementVisible(element: HTMLElement) {
  const style = window.getComputedStyle(element)
  return !element.hidden && style.display !== 'none' && style.visibility !== 'hidden'
    && (element.offsetParent !== null || element.getClientRects().length > 0 || style.position === 'fixed')
}

export function prepareDialog(dialog: HTMLElement) {
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

export function trapDialogTab(dialog: HTMLElement, event: KeyboardEvent) {
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

export function detailNavigationDirection(event: KeyboardEvent, dialog: HTMLElement): -1 | 1 | null {
  if (!dialog.matches('.detail-sheet-stage > aside') || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null
  const target = event.target
  if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return null
  if (event.key === 'ArrowLeft') return -1
  if (event.key === 'ArrowRight') return 1
  return null
}

export function useDialogAccessibility(openCount: ComputedRef<number>, closeTop: () => void, navigateDetail?: (direction: -1 | 1) => boolean) {
  let returnTarget: HTMLElement | null = null

  function visibleDialogs() {
    return [...document.querySelectorAll<HTMLElement>(DIALOG_SELECTOR)].filter(isElementVisible)
  }

  function prepareTopDialog() {
    const dialog = visibleDialogs().at(-1)
    if (dialog) prepareDialog(dialog)
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
    const direction = detailNavigationDirection(event, dialog)
    if (direction && navigateDetail?.(direction)) {
      event.preventDefault()
      return
    }
    if (event.key !== 'Tab') return
    trapDialogTab(dialog, event)
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
