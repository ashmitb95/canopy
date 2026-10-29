// System sounds, as in claude-notifier. Windows ignores volume; Linux plays freedesktop sounds.
const MAC_DIR = '/System/Library/Sounds'
export const SOUNDS = ['Basso', 'Blow', 'Bottle', 'Frog', 'Funk', 'Glass', 'Hero', 'Morse', 'Ping', 'Pop', 'Purr', 'Sosumi', 'Submarine', 'Tink'] as const

const LINUX_DIR = '/usr/share/sounds/freedesktop/stereo'
const LINUX: Record<string, string> = {
  Basso: 'dialog-warning',
  Blow: 'service-logout',
  Bottle: 'bell',
  Frog: 'message-new-instant',
  Funk: 'message-new-instant',
  Glass: 'bell',
  Hero: 'complete',
  Morse: 'message',
  Ping: 'message',
  Pop: 'dialog-information',
  Purr: 'service-login',
  Sosumi: 'dialog-warning',
  Submarine: 'alarm-clock-elapsed',
  Tink: 'bell'
}
const WINDOWS: Record<string, string> = { Basso: 'Windows Critical Stop', Hero: 'tada', Glass: 'chimes', Ping: 'notify', Funk: 'chord' }

export type Command = { file: string; args: string[] } | { shell: string }

const shQuote = (text: string) => `'${text.replace(/'/g, `'\\''`)}'`

export function soundCommand(platform: NodeJS.Platform, sound: string, volume: number): Command {
  if (platform === 'darwin') return { file: 'afplay', args: ['-v', String(volume), `${MAC_DIR}/${sound}.aiff`] }
  if (platform === 'win32') {
    const path = `C:\\Windows\\Media\\${WINDOWS[sound] ?? 'Windows Notify'}.wav`
    const script = `$s='${path.replace(/'/g, "''")}'; if(Test-Path $s){(New-Object Media.SoundPlayer $s).PlaySync()}`
    return { shell: `powershell -NoProfile -NonInteractive -EncodedCommand ${Buffer.from(script, 'utf16le').toString('base64')}` }
  }
  const path = shQuote(`${LINUX_DIR}/${LINUX[sound] ?? 'complete'}.oga`)
  return { shell: `pw-play --volume=${volume} ${path} 2>/dev/null || paplay --volume=${Math.round(volume * 65536)} ${path} 2>/dev/null` }
}
