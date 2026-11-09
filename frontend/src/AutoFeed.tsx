import {useCallback,useEffect,useMemo,useState} from 'react'
import {Activity,ArrowRight,BellRing,CheckCircle2,Clock,Info,LoaderCircle,Radio,RefreshCcw,ShieldCheck,Sparkles,TrendingDown,TrendingUp,WifiOff} from 'lucide-react'
import {autoSubscribe,getAutoFeed} from './api'
import {subscribeTickers,type LiveStatus} from './ws'
import type {AutoFeedResponse,AutoSignal,Ticker} from './types'
import {CoinLogo} from './CoinLogo'

const fmt = (v:number|null|undefined) => v == null || !Number.isFinite(v) ? '—' : '$'+new Intl.NumberFormat('en-US',{maximumFractionDigits:v>=100?2:v>=1?4:8}).format(v)
const date=(s:string)=>new Date(s).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})
const active=(s:AutoSignal)=>s.status==='ACTIVE'
function humanStatus(s:AutoSignal) {
  if(s.status==='ACTIVE') return s.tpReached ? `TP${s.tpReached} достигнут · в работе` : 'Отслеживается'
  return ({'TP3':'Все цели достигнуты','STOP':'Достигнут SL','AMBIGUOUS':'Неясный порядок TP/SL','STALE':'Неполная история','EXPIRED':'Истёк срок'} as Record<string,string>)[s.status] || s.status
}

/** Market monitoring only: prices move in real time, outcomes are audited on 1m candles. */
export function AutoFeed({authorized,favorites,tickers,onOpen,toast}:{authorized:boolean;favorites:string[];tickers:Ticker[];onOpen:(sig:AutoSignal)=>void;toast:(s:string)=>void}) {
  const [feed,setFeed]=useState<AutoFeedResponse|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [live,setLive]=useState<Record<string,{value:number;at:number}>>({})
  const [stream,setStream]=useState<LiveStatus>('connecting')
  const [filter,setFilter]=useState<'active'|'all'>('active')
  const [scope,setScope]=useState<'all'|'top'|'favorites'>('all')
  const [direction,setDirection]=useState<'ALL'|'LONG'|'SHORT'>('ALL')
  const [sortBy,setSortBy]=useState<'new'|'strength'|'volume'|'move'>('new')
  const [query,setQuery]=useState('')
  const [subBusy,setSubBusy]=useState(false)
  const load=useCallback(async()=>{
    try{setFeed(await getAutoFeed());setError('')}
    catch(e){setError((e as Error).message)}finally{setLoading(false)}
  },[])
  useEffect(()=>{void load();const t=setInterval(()=>void load(),12000);return()=>clearInterval(t)},[load])
  const entries=useMemo(()=>feed?.signals || [],[feed])
  const tickMap=useMemo(()=>Object.fromEntries(tickers.map(t=>[t.symbol,t])),[tickers]) as Record<string,Ticker>
  const topSet=useMemo(()=>new Set([...tickers].sort((a,b)=>b.volume24h-a.volume24h).slice(0,20).map(t=>t.symbol)),[tickers])
  const display=useMemo(()=>entries.filter(x=>
    (filter==='all'||active(x)) &&
    (scope==='all'||(scope==='top'?topSet.has(x.symbol):favorites.includes(x.symbol))) &&
    (direction==='ALL'||direction===x.side) &&
    x.symbol.toUpperCase().includes(query.trim().toUpperCase())
  ).sort((a,b)=>{
    if(sortBy==='strength')return (b.result.strength||0)-(a.result.strength||0) || b.id-a.id
    if(sortBy==='volume')return (tickMap[b.symbol]?.volume24h||0)-(tickMap[a.symbol]?.volume24h||0)||b.id-a.id
    if(sortBy==='move'){
      const m=(v:AutoSignal)=>Math.abs(100*((feed?.prices[v.symbol]||v.entry)/v.entry-1))
      return m(b)-m(a)||b.id-a.id
    }
    return b.id-a.id
  }),[entries,filter,scope,topSet,favorites,direction,query,sortBy,tickMap,feed])
  const symbols=useMemo(()=>[...new Set(display.filter(active).map(x=>x.symbol))].slice(0,12),[display])
  const symbolsKey=symbols.join(',')
  useEffect(()=>{
    if(!symbolsKey){setStream('offline');return}
    return subscribeTickers(symbolsKey.split(','),(sym,value)=>setLive(prev=>({...prev,[sym]:{value,at:Date.now()}})),setStream)
  },[symbolsKey])
  const resolved=entries.filter(x=>x.status==='TP3'||x.status==='STOP').length
  const scan=feed?.scanner
  const progress=scan?.total ? Math.min(100,Math.round(100*(scan.scanned||0)/scan.total)) : 0
  async function toggleSub(){
    if(!authorized){toast('Открой Mini App через Telegram для подписки на сообщения.');return}
    setSubBusy(true)
    try{const r=await autoSubscribe(!feed?.subscribed);setFeed(prev=>prev?{...prev,subscribed:r.enabled}:prev);toast(r.enabled?'Уведомления об автосигналах включены':'Уведомления выключены')}
    catch(e){toast((e as Error).message)}finally{setSubBusy(false)}
  }
  return <>
    <div className="section-header auto-header"><div><div className="eyebrow muted">AUTO SCANNER / PAPER TRACKING</div><h1>Автосигналы <span className="heading-dot">.</span></h1><p>Алгоритм последовательно проверяет все доступные USDT-фьючерсы BingX и отслеживает виртуальные TP / SL. Часть сценариев может не пройти фильтры.</p></div>
      <button className="outline-btn" onClick={()=>void load()}><RefreshCcw size={16}/> Обновить</button>
    </div>
    <div className="auto-toolbar panel"><div className="auto-stream"><Radio size={18}/><strong>Рыночная лента</strong><span className={'stream-tag '+stream}>{symbols.length&&stream==='live'?'LIVE · BingX':stream==='connecting'?'ПОДКЛЮЧЕНИЕ':stream==='reconnecting'?'ПЕРЕПОДКЛЮЧЕНИЕ':'ОБНОВЛЕНИЕ REST'}</span></div>
      <button disabled={subBusy} className={'outline-btn auto-sub '+(feed?.subscribed?'watch-active':'')} onClick={()=>void toggleSub()}>{subBusy?<LoaderCircle size={16} className="spin"/>:<BellRing size={16}/>} {feed?.subscribed?'Уведомления подключены':'Уведомлять в Telegram'}</button>
    </div>
    <div className="panel scanner-progress">
      <div className="scanner-progress-head"><div><b><Activity size={16}/> Сканирование рынка BingX</b><small>{scan?.total ? `Проверено ${scan.scanned} из ${scan.total} пар · проход #${(scan.round||0)+1}` : 'Получение списка инструментов…'}</small></div><strong>{scan?.total ? progress+'%' : '—'}</strong></div>
      <div className="scanner-progress-track"><span style={{width:progress+'%'}}/></div>
      <div className="scanner-progress-foot"><span>Последняя пара: {scan?.lastSymbol||'—'}</span><span>{scan?.lastCompleted ? 'Предыдущий обход: '+date(scan.lastCompleted) : 'Первый полный обход ещё не завершён'}</span></div>
      {scan?.error&&<div className="scan-error">Ошибка сканера: {scan.error}</div>}
    </div>
    <div className="auto-stats">
      <div className="panel auto-stat"><small>АКТИВНЫЕ</small><strong>{entries.filter(active).length}</strong><span>Сценариев в наблюдении</span></div>
      <div className="panel auto-stat"><small>ЗАВЕРШЁННЫЕ</small><strong>{resolved}</strong><span>TP3 или SL, без неоднозначных</span></div>
      <div className="panel auto-stat"><small>ПОСЛЕДНИЙ СКАН</small><strong className="auto-last">{scan?.lastUpdate?date(scan.lastUpdate):'—'}</strong><span>Последняя обновлённая позиция обхода</span></div>
    </div>
    <div className="auto-switch"><button className={filter==='active'?'selected':''} onClick={()=>setFilter('active')}>В работе</button><button className={filter==='all'?'selected':''} onClick={()=>setFilter('all')}>Вся история</button></div>
    <div className="panel auto-filter-panel">
      <div className="auto-filter-line"><div className="auto-filter-buttons">
        <button className={scope==='all'?'selected':''} onClick={()=>setScope('all')}>Все монеты</button>
        <button className={scope==='top'?'selected':''} onClick={()=>setScope('top')}>ТОП-20</button>
        <button className={scope==='favorites'?'selected':''} onClick={()=>setScope('favorites')}>Избранные</button>
      </div><div className="auto-filter-buttons">
        <button className={direction==='ALL'?'selected':''} onClick={()=>setDirection('ALL')}>Все</button>
        <button className={direction==='LONG'?'selected long-filter':''} onClick={()=>setDirection('LONG')}>LONG</button>
        <button className={direction==='SHORT'?'selected short-filter':''} onClick={()=>setDirection('SHORT')}>SHORT</button>
      </div></div>
      <div className="auto-filter-line"><input className="auto-search" placeholder="Поиск пары, например SOL" value={query} onChange={e=>setQuery(e.target.value)}/>
      <select className="auto-sort" value={sortBy} onChange={e=>setSortBy(e.target.value as typeof sortBy)}><option value="new">Сначала новые</option><option value="strength">Сильнее сигнал</option><option value="volume">Объём 24ч</option><option value="move">Движение от входа</option></select></div>
      <small className="auto-filter-caption">Найдено: {display.length} из {entries.length} сценариев · Виртуальный мониторинг</small>
    </div>
    {loading&&<div className="panel auto-empty"><LoaderCircle className="spin" size={30}/><b>Загружаем автосигналы…</b></div>}
    {!loading&&error&&<div className="panel auto-empty"><WifiOff size={30}/><b>Не удалось получить ленту</b><p>{error}</p><button className="outline-btn" onClick={()=>void load()}>Повторить</button></div>}
    {!loading&&!error&&!feed?.scannerEnabled&&<div className="auto-warning"><Info size={17}/> Фоновый сканер отключён на Railway: проверь ENABLE_WORKER и AUTO_SIGNALS_ENABLED.</div>}
    {!loading&&!error&&!display.length&&<div className="panel auto-empty"><Sparkles size={34}/><b>{filter==='active'?'Активных сценариев пока нет':'Лента пока пуста'}</b><p>Сканер последовательно проверяет все доступные пары по закрытым свечам. Если ни одна не прошла фильтры, лента может оставаться пустой.</p></div>}
    <div className="auto-feed-list">{!error&&display.map(item=>{
      const x=live[item.symbol]
      const px=x && Date.now()-x.at < 20000 ? x.value : feed?.prices[item.symbol]
      const fresh=!!(x && Date.now()-x.at < 20000)
      const change=px && item.entry ? 100*(px/item.entry-1) : null
      const scenarioMove=change==null?null:change*(item.side==='SHORT'?-1:1)
      const target=item.takeProfits[0]
      const progress=px && target ? Math.max(0,Math.min(100,100*(px-item.entry)/(target-item.entry))) : 0
      const distanceTarget=px && target ? (Math.abs(target-px)/px*100).toFixed(2):'—'
      const distanceStop=px ? (Math.abs(item.stopLoss-px)/px*100).toFixed(2):'—'
      return <div key={item.id} className={'panel auto-item '+(active(item)?'active':'settled')}>
        <div className="auto-item-top"><CoinLogo symbol={item.symbol}/><div className={'auto-side '+(item.side==='LONG'?'long':'short')}>{item.side==='LONG'?<TrendingUp size={19}/>:<TrendingDown size={19}/>} {item.side}</div><div className="auto-title"><strong>{item.symbol.replace('-',' / ')}</strong><span>{item.interval} · {date(item.createdAt)} · #{item.id}</span></div><span className={'auto-state '+(active(item)?'running':item.status==='TP3'?'success':'ended')}>{humanStatus(item)}</span></div>
        <div className="auto-price-panel"><div><small>ЦЕНА В МОМЕНТ СИГНАЛА</small><strong>{fmt(item.entry)}</strong></div><div><small>{fresh?'< LIVE PRICE >':'ПОСЛЕДНЯЯ КОТИРОВКА'}</small><strong>{fmt(px)}</strong></div><div><small>ДВИЖЕНИЕ ПО СЦЕНАРИЮ</small><strong className={scenarioMove==null?'':(scenarioMove>=0?'positive':'negative')}>{scenarioMove==null?'—':(scenarioMove>=0?'+':'')+scenarioMove.toFixed(2)+'%'}</strong></div></div>
        <div className="auto-progress-title"><span><Activity size={14}/> Виртуальная отработка сценария</span><b>{active(item)?'LIVE MONITOR':humanStatus(item)}</b></div>
        <div className="auto-track"><span className="auto-track-fill" style={{width:progress+'%',background:item.side==='LONG'?'#29d59b':'#f36d88'}}/></div>
        <div className="auto-track-legend"><span>До TP1: {distanceTarget}%</span><span>До SL: {distanceStop}%</span></div>
        <div className="auto-levels"><div className="auto-level entry"><small>ENTRY</small><b>{fmt(item.entry)}</b></div>{item.takeProfits.map((v,i)=><div key={i} className={'auto-level '+(i<item.tpReached?'reached':'target')}><small>{i<item.tpReached?<CheckCircle2 size={11}/>:null} TP{i+1}</small><b>{fmt(v)}</b></div>)}<div className="auto-level stop"><small>STOP LOSS</small><b>{fmt(item.stopLoss)}</b></div></div>
        <div className="auto-insight"><Sparkles size={16}/><p>{item.result.aiSummary || item.result.summary} <span>{item.result.reasons?.filter(r=>r.direction===item.side).slice(0,2).map(r=>r.text).join(' ')}</span></p></div>
        <div className="auto-actions"><span><Clock size={13}/> Исходы проверяются по завершённым минутным свечам</span><button className="outline-btn" onClick={()=>onOpen(item)}>Открыть график <ArrowRight size={15}/></button></div>
      </div>
    })}</div>
    <div className="source-note auto-disclaimer"><ShieldCheck size={16}/> Автосигналы — виртуальное отслеживание технических сценариев, не исполненные сделки. LIVE означает актуальную котировку, а TP/SL подтверждаются позже по минутным свечам. Если цена затронула TP и SL в одной свече, результат помечается как неоднозначный. Лента не гарантирует прибыльности; для текстовых AI-комментариев нужен отдельный ключ.</div>
  </>
}
