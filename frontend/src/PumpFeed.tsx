import {useCallback,useEffect,useMemo,useState} from 'react'
import {Activity,ArrowRight,BellRing,Clock3,Flame,Info,LoaderCircle,RefreshCcw,ShieldCheck,TrendingDown,TrendingUp,WifiOff} from 'lucide-react'
import {getPumpFeed,pumpSubscribe} from './api'
import {CoinLogo} from './CoinLogo'
import type {PumpFeedResponse,PumpEvent,Ticker} from './types'

const fmt=(v:number)=>'$'+new Intl.NumberFormat('en-US',{maximumFractionDigits:v>=100?2:v>=1?4:8}).format(v)
const fmtVol=(v:number)=>v>=1e6?'$'+(v/1e6).toFixed(1)+'M':v>=1000?'$'+(v/1000).toFixed(1)+'K':'$'+v.toFixed(0)
const date=(iso:string)=>new Date(iso).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})

export function PumpFeed({authorized,tickers,onOpen,toast}:{authorized:boolean;tickers:Ticker[];onOpen:(symbol:string)=>void;toast:(s:string)=>void}){
  const [data,setData]=useState<PumpFeedResponse|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [direction,setDirection]=useState<'ALL'|'PUMP'|'DUMP'>('ALL')
  const [query,setQuery]=useState('')
  const [sort,setSort]=useState<'new'|'change'|'volume'>('new')
  const load=useCallback(async()=>{try{setData(await getPumpFeed());setError('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}},[])
  useEffect(()=>{void load();const timer=setInterval(()=>void load(),12000);return()=>clearInterval(timer)},[load])
  const prices=useMemo(()=>Object.fromEntries(tickers.map(t=>[t.symbol,t.lastPrice])),[tickers]) as Record<string,number>
  const events=useMemo(()=>[...(data?.events||[])].filter(x=>(direction==='ALL'||direction===x.direction)&&x.symbol.toUpperCase().includes(query.toUpperCase())).sort((a,b)=>sort==='change'?Math.abs(b.changePercent)-Math.abs(a.changePercent):sort==='volume'?b.turnoverUsdt-a.turnoverUsdt:b.id-a.id),[data,query,direction,sort])
  async function toggle(){if(!authorized){toast('Открой Mini App через Telegram и начни диалог с ботом через /start');return}setBusy(true);try{const r=await pumpSubscribe(!data?.subscribed);setData(d=>d?{...d,subscribed:r.enabled}:d);toast(r.enabled?'PUMP/DUMP-уведомления включены':'PUMP/DUMP-уведомления отключены')}catch(e){toast((e as Error).message)}finally{setBusy(false)}}
  return <>
    <div className="section-header pump-header"><div><div className="eyebrow muted">PRICE MOVEMENT / BINGX</div><h1>Резкие движения <span className="heading-dot">.</span></h1><p>Обнаруженные PUMP и DUMP за ~5 минут. Это уже произошедшие изменения цены, а не прогноз направления.</p></div><button className="outline-btn" onClick={()=>void load()}><RefreshCcw size={15}/> Обновить</button></div>
    <div className="panel balanced-notice"><ShieldCheck size={17}/><span><b>BALANCED</b> · Оборот ≥ ${((data?.marketFilter?.min24hTurnoverUSDT??10000000)/1000000).toFixed(0)} млн/24ч · Старше {data?.marketFilter?.minListingAgeDays??30} дней · Без нестандартных пар{data?.marketFilter?.eligible!=null?` · ${data.marketFilter.eligible} пар`:''}</span></div>
    {data?.marketFilter?.error&&<div className="auto-warning"><Info size={16}/> Проверка фильтра: {data.marketFilter.error}</div>}
    <div className="panel pump-toolbar"><div className="pump-toolbar-title"><Flame size={20}/><div><b>Монитор аномалий</b><small>{data?.monitorEnabled?(data?.monitor.warmingUp?'Накопление котировок ~5 минут':'Мониторинг активен'):'Отключён на сервере'} · {data?.monitor.observed||0} пар в наблюдении</small></div></div><button disabled={busy} className={'outline-btn auto-sub '+(data?.subscribed?'watch-active':'')} onClick={()=>void toggle()}>{busy?<LoaderCircle size={16} className="spin"/>:<BellRing size={16}/>} {data?.subscribed?'Сообщения в Telegram: ВКЛ':'Уведомлять в Telegram'}</button></div>
    <div className="panel pump-threshold"><Activity size={16}/><span>Порог: <b>±{data?.criteria.minChangePercent??3}% за 5 минут</b></span><span>Объём: <b>{data?.criteria.minVolumeRatio??2}× выше среднего</b></span><span>Новые события после подтверждения по закрытым свечам</span></div>
    <div className="panel auto-filter-panel"><div className="auto-filter-line"><div className="auto-filter-buttons"><button className={direction==='ALL'?'selected':''} onClick={()=>setDirection('ALL')}>Все события</button><button className={direction==='PUMP'?'selected long-filter':''} onClick={()=>setDirection('PUMP')}>PUMP</button><button className={direction==='DUMP'?'selected short-filter':''} onClick={()=>setDirection('DUMP')}>DUMP</button></div><span className="pump-count">Найдено: {events.length}</span></div><div className="auto-filter-line"><input className="auto-search" placeholder="Поиск монеты: BTC, SOL..." value={query} onChange={e=>setQuery(e.target.value)}/><select className="auto-sort" value={sort} onChange={e=>setSort(e.target.value as typeof sort)}><option value="new">Сначала новые</option><option value="change">По силе движения</option><option value="volume">По объёму за 5м</option></select></div></div>
    {loading&&<div className="panel auto-empty"><LoaderCircle className="spin" size={30}/> Загружаем рыночные события…</div>}
    {!loading&&error&&<div className="panel auto-empty"><WifiOff size={30}/><b>Нет связи с монитором</b><p>{error}</p><button className="outline-btn" onClick={()=>void load()}>Повторить</button></div>}
    {!loading&&!error&&!data?.monitorEnabled&&<div className="auto-warning"><Info size={16}/> Для автоматического отслеживания включи ENABLE_WORKER=true и PUMP_MONITOR_ENABLED=true в Railway.</div>}
    {!loading&&!error&&!events.length&&<div className="panel auto-empty"><Flame size={32}/><b>Резких движений пока не обнаружено</b><p>После запуска монитор сначала собирает историю ~5 минут. Событие появится только при подтверждённом росте или падении цены и всплеске объёма. Отсутствие событий — нормальная ситуация.</p></div>}
    <div className="pump-list">{!error&&events.map((event:PumpEvent)=>{const last=prices[event.symbol];return <div className="panel pump-item" key={event.id}><div className="pump-item-head"><CoinLogo symbol={event.symbol}/><div className="pump-asset"><strong>{event.symbol.replace('-',' / ')}</strong><small><Clock3 size={12}/> {date(event.occurredAt)} · окно 5м</small></div><span className={'pump-tag '+(event.direction==='PUMP'?'up':'down')}>{event.direction==='PUMP'?<TrendingUp size={16}/>:<TrendingDown size={16}/>} {event.direction}</span></div><div className={'pump-change '+(event.direction==='PUMP'?'positive':'negative')}>{event.changePercent>0?'+':''}{event.changePercent.toFixed(2)}% <small>за ~5 минут</small></div><div className="pump-metrics"><div><small>НАЧАЛЬНАЯ ЦЕНА</small><b>{fmt(event.startPrice)}</b></div><div><small>ЦЕНА СОБЫТИЯ</small><b>{fmt(event.price)}</b></div><div><small>ТЕКУЩАЯ КОТИРОВКА</small><b>{last?fmt(last):'—'}</b></div><div><small>ОБЪЁМ 5М</small><b>{fmtVol(event.turnoverUsdt)}</b></div><div><small>ОБЪЁМ / СРЕДНИЙ</small><b>{event.volumeRatio.toFixed(1)}×</b></div></div><button className="outline-btn pump-chart-link" onClick={()=>onOpen(event.symbol)}>Открыть график <ArrowRight size={15}/></button></div>})}</div>
    <div className="source-note auto-disclaimer"><ShieldCheck size={16}/> PUMP/DUMP означает обнаруженный скачок цены, не доказательство манипуляции рынком и не сигнал покупать или продавать. События могут появляться с задержкой из-за сбора данных, проверки объёма и работы биржи. Уведомления приходят только после явной подписки в личный чат Telegram.</div>
  </>
}
