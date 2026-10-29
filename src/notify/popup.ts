import type { Command } from './sound'

/** An OS notification. On macOS, terminal-notifier makes a click bring VS Code forward (`focus` is the shell command it runs). */
export function popupCommand(
  platform: NodeJS.Platform,
  title: string,
  body: string,
  options: { terminalNotifier?: string; focus?: string }
): Command {
  if (platform === 'darwin') {
    if (options.terminalNotifier) {
      return { file: options.terminalNotifier, args: ['-title', title, '-message', body, ...(options.focus ? ['-execute', options.focus] : [])] }
    }
    const escape = (text: string) => text.replace(/[\\"]/g, '\\$&')
    return { file: 'osascript', args: ['-e', `display notification "${escape(body)}" with title "${escape(title)}"`] }
  }
  if (platform === 'win32') {
    const quote = (text: string) => text.replace(/'/g, "''")
    const script = `Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; $n.ShowBalloonTip(4000,'${quote(title)}','${quote(body)}',[System.Windows.Forms.ToolTipIcon]::None); Start-Sleep -m 500; $n.Dispose()`
    return { shell: `powershell -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(script, 'utf16le').toString('base64')}` }
  }
  return { file: 'notify-send', args: [title, body] }
}
