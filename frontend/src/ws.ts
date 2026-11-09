/** Documented public BingX USDT-M market stream. No API keys involved. */
import * as pako from 'pako'

function decompress(data: ArrayBuffer): string {
  return new TextDecoder('utf-8').decode(pako.ungzip(new Uint8Array(data)))
}

function connectSwapWsMarket(channels: string[], onMessage: (data: unknown) => void): WebSocket {
  const ws = new WebSocket('wss://open-api-swap.bingx.com/swap-market')
  ws.binaryType = 'arraybuffer'
  ws.onopen = () => {
    for (const ch of channels) {
      ws.send(JSON.stringify({id: crypto.randomUUID(),reqType:'sub',dataType:ch}))
    }
  }
  ws.onmessage = (event) => {
    let text: string
    try { text = typeof event.data === 'string' ? event.data : decompress(event.data as ArrayBuffer) }
    catch { return }
    if (text === 'Ping') { ws.send('Pong'); return }
    try { onMessage(JSON.parse(text)) }
    catch { onMessage(text) }
  }
  ws.onerror = () => {} // A retry is scheduled on close.
  return ws
}

/** Returns cleanup. Reconnects after short outages; REST polling is separate fallback. */
export function subscribeTicker(symbol: string, onPrice: (value:number) => void) {
  let disposed=false
  let socket:WebSocket|undefined
  let reconnect:ReturnType<typeof setTimeout>|undefined
  let failures=0
  function connect() {
    if(disposed)return
    try {
      socket=connectSwapWsMarket([`${symbol}@ticker`],(message)=>{
        const data=message as {dataType?:string,data?:{s?:string,c?:string}}
        if(data?.dataType!==`${symbol}@ticker`||data.data?.s!==symbol)return
        const next=Number(data.data.c)
        if(Number.isFinite(next)&&next>0){failures=0;onPrice(next)}
      })
      socket.onclose=()=>{
        if(!disposed){failures++;reconnect=setTimeout(connect,Math.min(30000,1500*2**Math.min(failures,5)))}
      }
    }catch {if(!disposed)reconnect=setTimeout(connect,10000)}
  }
  connect()
  return ()=>{disposed=true;if(reconnect)clearTimeout(reconnect);socket?.close()}
}
