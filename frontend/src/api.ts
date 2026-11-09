import type {Alert, Candle, SavedSignal, Settings, Signal, Ticker, Timeframe, Watch} from './types'

declare global {
  interface Window {Telegram?:{WebApp?:{initData:string;ready:()=>void;expand:()=>void;colorScheme?:string;HapticFeedback?:{impactOccurred:(style:string)=>void};openTelegramLink?:(link:string)=>void}}}
}
export const isTelegram = () => Boolean(window.Telegram?.WebApp?.initData)
export class ApiError extends Error {constructor(message:string, public status:number){super(message)}}
export async function api<T>(url:string, options:RequestInit={}):Promise<T> {
  const initData=window.Telegram?.WebApp?.initData
  const headers:Record<string,string>={'Content-Type':'application/json',...(initData?{'X-Telegram-Init-Data':initData}:{}),...(options.headers as Record<string,string>||{})}
  let res:Response
  try {res=await fetch(url,{...options,headers})} catch {throw new ApiError('Нет соединения с сервером. Проверьте интернет.',0)}
  const body=await res.json().catch(()=>({}))
  if(!res.ok)throw new ApiError(body.detail||`HTTP ${res.status}`,res.status)
  return body as T
}
export const getMarkets=(search='')=>api<{symbols:string[],total:number}>('/api/markets?search='+encodeURIComponent(search))
export const getTickers=()=>api<{tickers:Ticker[],updatedAt:number}>('/api/tickers')
export const getCoinLogos=()=>api<{images:Record<string,string>,count:number}>('/api/coin-logos')
export const getCandles=(symbol:string, interval:Timeframe)=>api<{candles:Candle[]}>('/api/candles?symbol='+encodeURIComponent(symbol)+'&interval='+interval)
export const getSparklines=(symbols:string[])=>api<{sparklines:Record<string,number[]>}>('/api/sparklines?symbols='+encodeURIComponent(symbols.join(',')))
export const getAnalysis=(symbol:string,interval:Timeframe)=>api<Signal>('/api/analyze',{method:'POST',body:JSON.stringify({symbol,interval,save:true})})
export const getMe=()=>api<Settings>('/api/me')
export const saveSettings=(input:Omit<Settings,'userId'|'chatConnected'>)=>api<{ok:boolean}>('/api/settings',{method:'POST',body:JSON.stringify(input)})
export const getFavorites=()=>api<{symbols:string[]}>('/api/favorites')
export const changeFavorite=(symbol:string,active:boolean)=>api<{ok:boolean}>('/api/favorites',{method:'POST',body:JSON.stringify({symbol,active})})
export const getHistory=()=>api<{history:SavedSignal[],stats:Record<string,number>,sampleSize:number}>('/api/history')
export const getAlerts=()=>api<{alerts:Alert[]}>('/api/alerts')
export const createAlert=(symbol:string,targetPrice:number)=>api<{ok:boolean}>('/api/alerts',{method:'POST',body:JSON.stringify({symbol,targetPrice})})
export const deleteAlert=(id:number)=>api<{ok:boolean}>('/api/alerts/'+id,{method:'DELETE'})
export const getWatches=()=>api<{watches:Watch[]}>('/api/watches')
export const changeWatch=(symbol:string,interval:Timeframe,active:boolean)=>api<{ok:boolean}>('/api/watches',{method:'POST',body:JSON.stringify({symbol,interval,active})})
export const getAutoFeed=()=>api<import('./types').AutoFeedResponse>('/api/auto-signals')
export const autoSubscribe=(enabled:boolean)=>api<{enabled:boolean}>('/api/auto-subscription',{method:'POST',body:JSON.stringify({enabled})})

export const getPumpFeed=()=>api<import('./types').PumpFeedResponse>('/api/pump-events')
export const pumpSubscribe=(enabled:boolean)=>api<{enabled:boolean}>('/api/pump-subscription',{method:'POST',body:JSON.stringify({enabled})})

export function getAutoHistory(filters:{page:number;pageSize:number;outcome:import('./types').HistoryOutcome;side:'ALL'|'LONG'|'SHORT';symbol:string;dateFrom:string;dateTo:string}){
 const params=new URLSearchParams({page:String(filters.page),page_size:String(filters.pageSize),outcome:filters.outcome,side:filters.side,symbol:filters.symbol,date_from:filters.dateFrom,date_to:filters.dateTo})
 return api<import('./types').AutoHistoryResponse>('/api/auto-history?'+params.toString())
}

// Authenticated virtual ledger; NO exchange keys or real-order endpoints.
export const getPaperAccount=()=>api<import('./types').PaperAccountResponse>('/api/paper')
export const setPaperEnabled=(enabled:boolean)=>api<{enabled:boolean}>('/api/paper/config',{method:'POST',body:JSON.stringify({enabled})})
export const resetPaper=()=>api<{ok:boolean}>('/api/paper/reset',{method:'POST'})
export const closePaperPosition=(id:number)=>api<{ok:boolean}>('/api/paper/positions/'+id+'/close',{method:'POST'})
