type PauseListener = (paused: boolean) => void
type UploadAttempt = (signal: AbortSignal) => Promise<Response>

export class UploadPauseController {
  private paused = false
  private controllers = new Set<AbortController>()
  private waiters: Array<() => void> = []

  constructor(private readonly onChange: PauseListener) {}

  pause(): void {
    if (this.paused) return
    this.paused = true
    this.onChange(true)
    this.controllers.forEach(controller => controller.abort())
    this.controllers.clear()
  }

  resume(): void {
    this.paused = false
    this.onChange(false)
    const waiters = this.waiters
    this.waiters = []
    waiters.forEach(resolve => resolve())
  }

  private async waitForResume(): Promise<void> {
    if (!this.paused) return
    await new Promise<void>(resolve => this.waiters.push(resolve))
  }

  async request(attempt: UploadAttempt, failureMessage: string): Promise<void> {
    while (true) {
      await this.waitForResume()
      const controller = new AbortController()
      this.controllers.add(controller)
      try {
        const response = await attempt(controller.signal)
        if (!response.ok) throw new Error(failureMessage)
        return
      } catch (error) {
        if (controller.signal.aborted) continue
        throw error
      } finally {
        this.controllers.delete(controller)
      }
    }
  }
}
