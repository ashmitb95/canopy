type Sink = (line: string, reveal?: boolean) => void

let sink: Sink = () => {}

/** Binds where log lines go. The extension sends them to the Canopy output channel; tests and headless git keep the default no-op. */
export function setLog(next: Sink): void {
  sink = next
}

export function log(line: string, reveal = false): void {
  sink(line, reveal)
}
