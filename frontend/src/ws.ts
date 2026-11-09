/** BingX official public USDT-M swap stream. Read-only: no user keys or order placement. */
import * as pako from 'pako'
import type {Candle, Timeframe} from './types'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'offline'

type JsonRecord = Record<string, unknown>
const WS_URL = 'wss://open-api-swap.bingx.com/swap-market'

function parsePayload(raw: unknown): JsonRecord | null {
  let message: string
  try {
    if (typeof raw === 'string') message = raw
    else if (raw instanceof ArrayBuffer) message = new TextDecoder().decode(pako.ungzip(new Uint8Array(raw)))
    else return null
    if (message === 'Ping') return {heartbeat: true}
    const parsed: unknown = JSON.parse(message)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as JsonRecord : null
  } catch { return null }
}

/** Reconnect, resubscribe, heartbeat reply, and notify only after real payloads arrive. */
export function subscribePublic(channels: string[], onData: (data: JsonRecord) => void,
  onStatus?: (status: LiveStatus) => void): () => void {
  let disposed = false
  let ws: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let watchdog: ReturnType<typeof setInterval> | undefined
  let attempts = 0
  let lastUpdate = Date.now()
  const report = (status: LiveStatus) => { if (!disposed) onStatus?.(status) }
  function connect() {
    if (disposed) return
    report(attempts ? 'reconnecting' : 'connecting')
    lastUpdate = Date.now()
    try {
      ws = new WebSocket(WS_URL)
      ws.binaryType = 'arraybuffer'
      ws.onopen = () => {
        if (disposed) return
        channels.forEach(dataType => ws?.send(JSON.stringify({id: crypto.randomUUID(),reqType:'sub',dataType})))
        watchdog = setInterval(() => {
          // If the connection is silent, reconnect. A successful socket opening
          // is not proof that market subscriptions are actually delivering.
          if (Date.now() - lastUpdate > 45000) ws?.close()
        }, 10000)
      }
      ws.onmessage = (ev) => {
        const payload = parsePayload(ev.data)
        if (!payload) return
        lastUpdate = Date.now()
        if (payload.heartbeat) {if (ws?.readyState === WebSocket.OPEN) ws.send('Pong');return}
        if (payload.dataType && payload.data) {
          attempts = 0
          report('live')
          onData(payload)
        }
      }
      ws.onerror = () => { if (ws?.readyState !== WebSocket.CLOSED) ws?.close() }
      ws.onclose = () => {
        if (watchdog) clearInterval(watchdog)
        if (disposed) return
        attempts++
        report('offline')
        retry = setTimeout(connect, Math.min(30000, 1500 * 2 ** Math.min(attempts, 5)))
      }
    } catch {
      attempts++
      report('offline')
      retry = setTimeout(connect, Math.min(30000, 1500 * 2 ** Math.min(attempts, 5)))
    }
  }
  connect()
  return () => {
    disposed = true
    if (retry) clearTimeout(retry)
    if (watchdog) clearInterval(watchdog)
    ws?.close()
  }
}

function finitePositive(input: unknown): number | null {
  const n = Number(input)
  return Number.isFinite(n) && n > 0 ? n : null
}

/** Per-symbol ticker stream with one socket for multiple monitored symbols. */
export function subscribeTickers(symbols: string[], onPrice: (symbol: string, price: number) => void,
  onStatus?: (s: LiveStatus) => void): () => void {
  const unique = [...new Set(symbols)].filter(s => /^[A-Z0-9]+-USDT$/.test(s)).slice(0, 12)
  if (!unique.length) return () => {}
  const channels = new Set(unique.map(s => `${s}@ticker`))
  return subscribePublic([...channels], msg => {
    if (typeof msg.dataType !== 'string' || !channels.has(msg.dataType)) return
    const obj = msg.data as JsonRecord
    const symbol = msg.dataType.split('@')[0]
    if (obj.s !== symbol) return
    const price = finitePositive(obj.c)
    if (price !== null) onPrice(symbol, price)
  }, onStatus)
}

export function subscribeTicker(symbol: string, onPrice: (value: number) => void,
  onStatus?: (s: LiveStatus) => void): () => void {
  return subscribeTickers([symbol], (_, value) => onPrice(value), onStatus)
}

/** Parses BingX's documented `data.K` OHLCV stream (milliseconds). */
export function parseKline(msg: JsonRecord, symbol: string, interval: Timeframe): Candle | null {
  if (msg.dataType !== `${symbol}@kline_${interval}`) return null
  const data = msg.data as JsonRecord | undefined
  if (!data || data.s !== symbol) return null
  const k = data.K as JsonRecord | undefined
  if (!k) return null
  const time = Number(k.t), closeTime = Number(k.T)
  const open = finitePositive(k.o), high = finitePositive(k.h)
  const low = finitePositive(k.l), close = finitePositive(k.c)
  const volume = Number(k.v)
  if (![time, closeTime, volume].every(Number.isFinite) || time <= 0 || volume < 0 ||
      open === null || high === null || low === null || close === null || low > Math.min(open, close) || high < Math.max(open, close)) return null
  return {time, closeTime, open, high, low, close, volume}
}

export function subscribeKlines(symbol: string, interval: Timeframe, onCandle: (candle: Candle) => void,
  onStatus?: (s: LiveStatus) => void): () => void {
  return subscribePublic([`${symbol}@kline_${interval}`], msg => {
    const candle = parseKline(msg, symbol, interval)
    if (candle) onCandle(candle)
  }, onStatus)
}
