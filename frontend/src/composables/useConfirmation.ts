import { computed, ref } from 'vue'

type ConfirmAction = () => void | Promise<void>

export function useConfirmation(onError: (message: string) => void) {
  const confirmOpen = ref(false)
  const confirmMessage = ref('')
  const confirmUsageImpact = ref<any | null>(null)
  const deleteConfirmationStage = ref(0)
  const confirmBusy = ref(false)
  let pendingConfirmAction: ConfirmAction | null = null

  const confirmTitle = computed(() => confirmMessage.value.includes('覆盖原文件') ? '覆盖确认' : confirmMessage.value.includes('撤销关联') ? '撤销确认' : confirmMessage.value.includes('还原') ? '还原确认' : '删除确认')
  const confirmActionText = computed(() => deleteConfirmationStage.value === 2 ? '确认' : confirmMessage.value.includes('覆盖原文件') ? '确定' : confirmMessage.value.includes('撤销关联') ? '确认撤销' : confirmMessage.value.includes('还原') ? '确认还原' : confirmMessage.value.includes('清空回收站') ? '确认清空' : '确认删除')

  function askConfirmation(message: string, action: ConfirmAction, usageImpact: any | null = null) {
    confirmMessage.value = message
    confirmUsageImpact.value = usageImpact
    deleteConfirmationStage.value = 0
    pendingConfirmAction = action
    confirmOpen.value = true
  }

  async function runConfirmedAction() {
    if (!pendingConfirmAction) return
    if (deleteConfirmationStage.value === 1 && confirmUsageImpact.value?.affected_count) {
      deleteConfirmationStage.value = 2
      confirmMessage.value = '被删除素材的关联关系会一并清除，确认继续吗？'
      return
    }
    const action = pendingConfirmAction
    const dismissBeforeAction = confirmMessage.value.includes('覆盖原文件')
    confirmBusy.value = true
    if (dismissBeforeAction) {
      confirmOpen.value = false
      confirmUsageImpact.value = null
      deleteConfirmationStage.value = 0
      pendingConfirmAction = null
    }
    try {
      await action()
      if (!dismissBeforeAction) {
        confirmOpen.value = false
        confirmUsageImpact.value = null
        deleteConfirmationStage.value = 0
        pendingConfirmAction = null
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : '操作失败')
    } finally {
      confirmBusy.value = false
    }
  }

  function cancelConfirmation() {
    if (confirmBusy.value) return
    confirmOpen.value = false
    confirmUsageImpact.value = null
    deleteConfirmationStage.value = 0
    pendingConfirmAction = null
  }

  return {
    confirmOpen, confirmMessage, confirmUsageImpact, deleteConfirmationStage, confirmBusy,
    confirmTitle, confirmActionText, askConfirmation, runConfirmedAction, cancelConfirmation,
  }
}
