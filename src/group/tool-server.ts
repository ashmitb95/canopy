// One local MCP server over HTTP, reachable from any provider's CLI. Only agents AgentDeck started know its address.
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

export type Tool = { name: string; description: string; inputSchema: Record<string, unknown>; call: (args: Record<string, unknown>, caller: string) => Promise<string> | string }
export type ToolServer = { url: string; close(): void; methods: string[] }

export async function startToolServer(tools: Tool[]): Promise<ToolServer> {
  const methods: string[] = []
  const server: Server = createServer((req, res) => {
    if (req.method !== 'POST') {
      res.writeHead(405).end()
      return
    }
    let body = ''
    req.on('data', (chunk) => (body += chunk))
    req.on('end', async () => {
      const message = JSON.parse(body) as { id?: number | string; method: string; params?: { protocolVersion?: string; name?: string; arguments?: Record<string, unknown> } }
      methods.push(message.method)
      if (message.id === undefined) {
        res.writeHead(202).end()
        return
      }
      const reply = (result: unknown) => {
        res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }))
      }
      if (message.method === 'initialize') return reply({ protocolVersion: message.params?.protocolVersion ?? '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'agentdeck', version: '0.0.1' } })
      if (message.method === 'ping') return reply({})
      if (message.method === 'tools/list') return reply({ tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })) })
      if (message.method === 'tools/call') {
        const tool = tools.find((candidate) => candidate.name === message.params?.name)
        if (!tool) return reply({ isError: true, content: [{ type: 'text', text: 'Unknown tool' }] })
        return reply({ content: [{ type: 'text', text: await tool.call(message.params?.arguments ?? {}, req.url ?? '') }] })
      }
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id: message.id, error: { code: -32601, message: 'Method not found' } }))
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo
  return { url: `http://127.0.0.1:${port}/mcp`, close: () => server.close(), methods }
}
