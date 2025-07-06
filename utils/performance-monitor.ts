export class PerformanceMonitor {
    private metrics = new Map<string, number[]>();
    
    startTimer(operation: string): () => void {
        const start = performance.now();
        return () => {
            const duration = performance.now() - start;
            this.recordMetric(operation, duration);
        };
    }
    
    private recordMetric(operation: string, duration: number): void {
        if (!this.metrics.has(operation)) {
            this.metrics.set(operation, []);
        }
        const times = this.metrics.get(operation)!;
        times.push(duration);
        
        if (times.length > 100) {
            times.shift();
        }
    }
    
    getAverageTime(operation: string): number {
        const times = this.metrics.get(operation) || [];
        if (times.length === 0) return 0;
        return times.reduce((a, b) => a + b, 0) / times.length;
    }
    
    getMetricsSummary(): Record<string, {avg: number, count: number}> {
        const summary: Record<string, {avg: number, count: number}> = {};
        for (const [operation, times] of this.metrics.entries()) {
            summary[operation] = {
                avg: this.getAverageTime(operation),
                count: times.length
            };
        }
        return summary;
    }
}