export class LongPoller {
  private running = false;
  private foreground = true;
  private timer: number | null = null;
  private generation = 0;
  private errorStreak = 0;
  private readonly tickFn: () => Promise<'changed' | 'timeout' | 'stop'>;
  private readonly onError?: (err: Error) => void;

  constructor(
    tickFn: () => Promise<'changed' | 'timeout' | 'stop'>,
    onError?: (err: Error) => void,
  ) {
    this.tickFn = tickFn;
    this.onError = onError;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.errorStreak = 0;
    this.generation += 1;
    void this.loop(this.generation);
  }

  stop(): void {
    this.running = false;
    this.generation += 1;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  setForeground(active: boolean): void {
    if (this.foreground === active) return;
    this.foreground = active;
    if (!this.running) return;
    if (active) {
      this.errorStreak = 0;
      this.generation += 1;
      if (this.timer !== null) {
        clearTimeout(this.timer);
        this.timer = null;
      }
      void this.loop(this.generation);
    } else {
      this.generation += 1;
      if (this.timer !== null) {
        clearTimeout(this.timer);
        this.timer = null;
      }
    }
  }

  private schedule(gen: number, delayMs: number): void {
    if (!this.running || !this.foreground || gen !== this.generation) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.loop(gen);
    }, delayMs) as unknown as number;
  }

  private async loop(gen: number): Promise<void> {
    if (!this.running || !this.foreground || gen !== this.generation) return;
    try {
      const outcome = await this.tickFn();
      if (!this.running || !this.foreground || gen !== this.generation) return;
      this.errorStreak = 0;
      if (outcome === 'stop') {
        this.stop();
        return;
      }
      this.schedule(gen, outcome === 'changed' ? 40 : 100);
    } catch (err) {
      if (!this.running || !this.foreground || gen !== this.generation) return;
      this.errorStreak += 1;
      if (this.onError) {
        this.onError(err instanceof Error ? err : new Error(String(err)));
      }
      const backoff = Math.min(8000, 1000 * Math.pow(2, Math.min(3, this.errorStreak - 1)));
      this.schedule(gen, backoff);
    }
  }
}
