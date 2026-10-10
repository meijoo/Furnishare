/** Bounded set with least-recently-used eviction (Map preserves insertion order). */
export class LruSet {
  private readonly items = new Map<string, true>();

  constructor(private readonly max: number) {}

  has(key: string): boolean {
    if (!this.items.has(key)) return false;
    this.items.delete(key);
    this.items.set(key, true);
    return true;
  }

  add(key: string): void {
    this.items.delete(key);
    this.items.set(key, true);
    while (this.items.size > this.max) {
      const oldest = this.items.keys().next().value;
      if (oldest === undefined) break;
      this.items.delete(oldest);
    }
  }

  delete(key: string): void {
    this.items.delete(key);
  }

  get size(): number {
    return this.items.size;
  }
}
