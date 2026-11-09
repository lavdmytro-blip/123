import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react'
import {createRoot} from 'react-dom/client'
import {motion,AnimatePresence} from 'framer-motion'
import {Activity,ArrowDownRight,ArrowRight,ArrowUpRight,Bell,BellRing,Check,ChevronDown,Clock,Compass,Heart,History,Info,LoaderCircle,LockKeyhole,Plus,RefreshCcw,Search,Settings2,ShieldCheck,SlidersHorizontal,Sparkles,Target,Trash2,TrendingDown,TrendingUp,Wifi,X,XCircle} from 'lucide-react'
import {changeFavorite,changeWatch,createAlert,deleteAlert,getAlerts,getAnalysis,getCandles,getFavorites,getHistory,getMarkets,getMe,getSparklines,getTickers,getWatches,isTelegram,saveSettings} from './api'
import {MarketChart,Sparkline} from './chart'
import {SignalsHub} from './SignalsHub'
import {CoinLogo,CoinLogoProvider} from './CoinLogo'
import {subscribeTicker,subscribeKlines,type LiveStatus} from './ws'
import type {Alert,Candle,AutoSignal,SavedSignal,Settings,Side,Signal,Tab,Ticker,Timeframe,Watch} from './types'
import './style.css'

const popular=['BTC-USDT','ETH-USDT','SOL-USDT','XRP-USDT','BNB-USDT','DOGE-USDT','ADA-USDT','AVAX-USDT']
const intervals:Timeframe[]=['1m','5m','15m','30m','1h','4h','1d']
const tabs:{id:Tab,label:string,icon:typeof Compass}[]=[{id:'home',label:'Обзор',icon:Compass},{id:'terminal',label:'Терминал',icon:Activity},{id:'history',label:'История',icon:History},{id:'alerts',label:'Уведомления',icon:Bell},{id:'auto',label:'AI Сигналы',icon:Sparkles},{id:'settings',label:'Настройки',icon:Settings2}]
const number=(v:number|null|undefined,digits=4)=>v==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits}).format(v)
const price=(v:number|null|undefined)=>v==null?'—':'$'+number(v,v>100?2:v>1?4:8)
const usd=(v:number|null|undefined)=>v==null?'—':v>=1e9?'$'+(v/1e9).toFixed(2)+'B':v>=1e6?'$'+(v/1e6).toFixed(2)+'M':v>=1e3?'$'+(v/1e3).toFixed(2)+'K':'$'+number(v,2)
const date=(x:number|string)=>new Date(x).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})
const cls=(side:Side)=>side==='LONG'?'long':side==='SHORT'?'short':'wait'

function mergeHistory(base:Candle[],incoming:Candle[]):Candle[]{
 // Timestamp-keyed merge: only the latest 310 bars are retained; no time-frame cross-talk.
 const map=new Map(base.map(c=>[c.time,c]))
 for(const c of incoming){if(Number.isFinite(c.time)&&c.time>0)map.set(c.time,c)}
 return [...map.values()].sort((a,b)=>a.time-b.time).slice(-310)
}

function App(){
 const [tab,setTab]=useState<Tab>(()=>/^([A-Z0-9]{2,18})-USDT$/.test(new URLSearchParams(window.location.search).get('symbol')||'')?'terminal':'home')
 const [allSymbols,setAllSymbols]=useState<string[]>([])
 const [tickers,setTickers]=useState<Ticker[]>([])
 const [livePrice,setLivePrice]=useState<{symbol:string,price:number}|null>(null)
 const [sparks,setSparks]=useState<Record<string,number[]>>({})
 const [search,setSearch]=useState('')
 const [symbol,setSymbol]=useState(()=>{const candidate=new URLSearchParams(window.location.search).get('symbol')||'';return /^[A-Z0-9]{2,18}-USDT$/.test(candidate)?candidate:'BTC-USDT'})
 const [interval,setInterval]=useState<Timeframe>('15m')
 const [candles,setCandles]=useState<Candle[]>([])
 const [result,setResult]=useState<Signal|null>(null)
 const [archived,setArchived]=useState(false)
 const [busy,setBusy]=useState(false)
 const [chartBusy,setChartBusy]=useState(false)
 const [chartStream,setChartStream]=useState<LiveStatus>('connecting')
 const lastKlineRef=useRef(0)
 const [marketBusy,setMarketBusy]=useState(true)
 const [error,setError]=useState('')
 const [toast,setToast]=useState('')
 const [favorites,setFavorites]=useState<string[]>([])
 const [history,setHistory]=useState<SavedSignal[]>([])
 const [stats,setStats]=useState<Record<string,number>>({})
 const [alerts,setAlerts]=useState<Alert[]>([])
 const [watches,setWatches]=useState<Watch[]>([])
 const [target,setTarget]=useState('')
 const [settings,setSettings]=useState<Settings>({userId:0,language:'ru',theme:'dark',interval:'15m',notifications:true,chatConnected:false})
 const [searchOpen,setSearchOpen]=useState(false)
 const authorized=isTelegram()
 const tickMap=useMemo(()=>Object.fromEntries(tickers.map(t=>[t.symbol,t])),[tickers]) as Record<string,Ticker>
 const thisTick={...tickMap[symbol],...(livePrice?.symbol===symbol?{lastPrice:livePrice.price}:{})} as Ticker
 const showToast=(s:string)=>{setToast(s);window.setTimeout(()=>setToast(''),4000)}
 const loadMarket=useCallback(async()=>{
  try{const [pairs,data]=await Promise.all([getMarkets(),getTickers()]);setAllSymbols(pairs.symbols);setTickers(data.tickers);setError('')}
  catch(e){setError((e as Error).message)}finally{setMarketBusy(false)}
 },[])
 const loadPrivate=useCallback(async()=>{
  if(!authorized)return
  const responses=await Promise.allSettled([getMe(),getFavorites(),getHistory(),getAlerts(),getWatches()])
  if(responses[0].status==='fulfilled'){setSettings(responses[0].value);setInterval(responses[0].value.interval)}
  if(responses[1].status==='fulfilled')setFavorites(responses[1].value.symbols)
  if(responses[2].status==='fulfilled'){setHistory(responses[2].value.history);setStats(responses[2].value.stats)}
  if(responses[3].status==='fulfilled')setAlerts(responses[3].value.alerts)
  if(responses[4].status==='fulfilled')setWatches(responses[4].value.watches)
 },[authorized])
 useEffect(()=>{window.Telegram?.WebApp?.ready();window.Telegram?.WebApp?.expand();void loadMarket();void loadPrivate();const timer=window.setInterval(()=>void loadMarket(),20000);return()=>window.clearInterval(timer)},[loadMarket,loadPrivate])
 useEffect(()=>{const present=popular.filter(p=>allSymbols.includes(p));if(!present.length)return;getSparklines(present).then(x=>setSparks(x.sparklines)).catch(()=>{})},[allSymbols])
 useEffect(()=>{
   if(tab!=='terminal'&&tab!=='home')return
   let cancelled=false
   lastKlineRef.current=0
   setChartStream('connecting')
   setCandles([])
   setChartBusy(true)
   // On each symbol/timeframe change load a fresh, corresponding 310-bar history.
   async function update(initial=false){
     try{const data=await getCandles(symbol,interval)
       if(cancelled)return
       if(initial){setCandles(prev=>{const newer=prev.filter(c=>c.time>=data.candles.at(-1)?.time!);return newer.length?mergeHistory(data.candles,newer):data.candles})}
       else if(Date.now()-lastKlineRef.current>15000){setCandles(prev=>mergeHistory(data.candles,prev.filter(c=>c.time>=data.candles.at(-1)?.time!)))}
       setError('')
     }catch(e){if(!cancelled){setError((e as Error).message)}}
     finally{if(!cancelled)setChartBusy(false)}
   }
   void update(true)
   // REST fallback if market WebSocket stream is unavailable. No fake LIVE badge.
   const timer=window.setInterval(()=>{if(Date.now()-lastKlineRef.current>15000)void update(false)},20000)
   const unsub=subscribeKlines(symbol,interval,(c)=>{
      lastKlineRef.current=Date.now()
      setCandles(prev=>mergeHistory(prev,[c]))
   },s=>{if(!cancelled)setChartStream(s)})
   return()=>{cancelled=true;window.clearInterval(timer);unsub()}
 },[symbol,interval,tab])
 useEffect(()=>{document.documentElement.dataset.theme=settings.theme},[settings.theme])
 useEffect(()=>subscribeTicker(symbol,(v)=>setLivePrice({symbol,price:v})),[symbol])
 const filtered=useMemo(()=>{
  const q=search.trim().toUpperCase().replace('/','-');return allSymbols.filter(x=>x.includes(q)).slice(0,120)
 },[allSymbols,search])
 const displayed=useMemo(()=>{
  const matches=filtered.filter(x=>tickMap[x]);
  return search?matches.slice(0,20):[...popular.filter(x=>matches.includes(x)),...matches.filter(x=>!popular.includes(x)).slice(0,5)]
 },[filtered,search,tickMap])
 function choose(sym:string){setSymbol(sym);setTab('terminal');setResult(null);setArchived(false);setSearchOpen(false);setSearch('');window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light')}
 async function analyzeNow(){setBusy(true);setArchived(false);setResult(null);try{const data=await getAnalysis(symbol,interval);setResult(data);setError('');if(authorized){const h=await getHistory().catch(()=>null);if(h){setHistory(h.history);setStats(h.stats)}}}catch(e){setError((e as Error).message);showToast((e as Error).message)}finally{setBusy(false)}}
 async function toggleFavorite(s:string){if(!authorized)return showToast('Открой приложение через Telegram для избранного.');const active=!favorites.includes(s);try{await changeFavorite(s,active);setFavorites(old=>active?[...old,s]:old.filter(x=>x!==s));showToast(active?'Добавлено в избранное':'Удалено из избранного')}catch(e){showToast((e as Error).message)}}
 async function toggleWatch(){if(!authorized)return showToast('Открой приложение через Telegram');const isActive=watches.some(x=>x.symbol===symbol&&x.interval===interval);try{await changeWatch(symbol,interval,!isActive);const ws=await getWatches();setWatches(ws.watches);showToast(isActive?'Отслеживание отключено':'Включено отслеживание новых сценариев')}catch(e){showToast((e as Error).message)}}
 async function addAlert(e:React.FormEvent){e.preventDefault();if(!authorized)return showToast('Открой приложение через Telegram');const v=Number(target.replace(',','.'));if(!Number.isFinite(v)||v<=0)return showToast('Введите корректную цену');try{await createAlert(symbol,v);const data=await getAlerts();setAlerts(data.alerts);setTarget('');showToast('Уведомление создано')}catch(err){showToast((err as Error).message)}}
 async function removeAlert(id:number){try{await deleteAlert(id);setAlerts(x=>x.filter(a=>a.id!==id));showToast('Уведомление удалено')}catch(e){showToast((e as Error).message)}}
 async function patchSettings(patch:Partial<Settings>){const next={...settings,...patch};setSettings(next);if(patch.interval)setInterval(patch.interval);if(authorized){try{await saveSettings({language:next.language,theme:next.theme,interval:next.interval,notifications:next.notifications});showToast('Настройки сохранены')}catch(e){showToast((e as Error).message)}}}
 const watching=watches.some(x=>x.symbol===symbol&&x.interval===interval)
 return <div className="app-shell">
  <aside className="sidebar">
   <div className="brand"><div className="brand-mark"><Activity size={21} strokeWidth={2.8}/></div><div className="brand-text"><strong>BINGX <span>AI</span></strong><small>SIGNALS TERMINAL</small></div></div>
   <div className="side-section">WORKSPACE</div><nav className="side-nav">{tabs.map(t=><button key={t.id} onClick={()=>setTab(t.id)} className={'side-link '+(tab===t.id?'selected':'')}><t.icon size={19}/><span>{t.label}</span>{t.id==='alerts'&&alerts.some(a=>a.active)&&<i className="nav-dot"/>}</button>)}</nav>
   <div className="sidebar-bottom"><div className="terminal-status"><span className="status-light"/> Режим анализа <small>READ ONLY</small></div><div className="sidebar-footnote">Данные BingX · Без исполнения ордеров</div></div>
  </aside>
  <main className="main">
   <div className="topbar"><div className="topbar-left"><span className="crumb">WORKSPACE</span><span className="slash">/</span><strong>{tabs.find(t=>t.id===tab)?.label}</strong></div><div className="topbar-right"><span className="live-pill"><span className="status-light"/>{error?'API ERROR':'BINGX DATA'}</span><button className="circle-btn" aria-label="Обновить" onClick={()=>void loadMarket()}><RefreshCcw size={17}/></button><div className="user-avatar">{authorized?'TG':'G'}</div></div></div>
   <div className="main-inner">
    <AnimatePresence mode="wait"><motion.div key={tab} initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-8}} transition={{duration:0.18}}>
    {tab==='home'&&<>
      <div className="hero"><div className="hero-glow"/><div className="eyebrow"><Sparkles size={14}/> INTELLIGENT MARKET ANALYSIS</div><h1>Рынок под контролем.<br/><span>Решения на основе данных.</span></h1><p>Технические сценарии для криптовалют BingX. Индикаторы, уровни и прозрачные аргументы без догадок.</p><button className="primary-btn" onClick={()=>setTab('terminal')}>Открыть терминал <ArrowRight size={17}/></button><div className="hero-ornament"><Activity size={170} strokeWidth={0.45}/></div></div>
      <div className="section-header"><div><h2>Обзор рынка</h2><p>Актуальные бессрочные пары · BingX</p></div><div className="detail-count">{tickers.length} инструментов</div></div>
      <div className="metrics-row"><div className="stat-card"><div className="stat-label"><Activity size={15}/> ДОСТУПНЫЕ ПАРЫ</div><div className="stat-big">{allSymbols.length||'—'}</div><div className="stat-sub">Из каталога BingX</div></div><div className="stat-card"><div className="stat-label"><TrendingUp size={15}/> РОСТ ЗА 24 ЧАСА</div><div className="stat-big positive">{tickers.length?tickers.filter(t=>t.change24h>0).length:'—'}</div><div className="stat-sub">Среди загруженных пар</div></div><div className="stat-card"><div className="stat-label"><TrendingDown size={15}/> СНИЖЕНИЕ ЗА 24 ЧАСА</div><div className="stat-big negative">{tickers.length?tickers.filter(t=>t.change24h<0).length:'—'}</div><div className="stat-sub">Среди загруженных пар</div></div></div>
      <div className="section-header markets-heading"><div><h2>Криптовалюты</h2><p>Выберите монету для подробного анализа</p></div><div className="search-inline"><Search size={17}/><input placeholder="Поиск BTC, ETH, SOL..." value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button className="icon-plain" onClick={()=>setSearch('')}><X size={15}/></button>}</div></div>
      <div className="market-panel"><div className="market-table-head"><span>АКТИВ</span><span>ЦЕНА</span><span>24H</span><span>ГРАФИК</span><span/></div>
        {marketBusy&&<div className="skeleton-list">{Array.from({length:6},(_,i)=><div key={i} className="skeleton-row"/>)}</div>}
        {!marketBusy&&displayed.length===0&&<div className="empty-text">{error||'Нет монет по вашему запросу'}</div>}
        {displayed.map(t=>{const x=tickMap[t];return <div className="market-row" key={t} onClick={()=>choose(t)} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')choose(t)}}><div className="asset-cell"><CoinLogo symbol={t}/><div><strong>{t.split('-')[0]}</strong><small>USDT · Perpetual</small></div></div><div className="price-cell"><strong>{price(x.lastPrice)}</strong><small>≈ {number(x.lastPrice,6)}</small></div><div className={x.change24h>=0?'change positive':'change negative'}>{x.change24h>=0?<ArrowUpRight size={15}/>:<ArrowDownRight size={15}/>} {Math.abs(x.change24h).toFixed(2)}%</div><Sparkline values={sparks[t]||[]} positive={x.change24h>=0}/><div className="row-end"><button className={'heart-btn '+(favorites.includes(t)?'hearted':'')} onClick={e=>{e.stopPropagation();void toggleFavorite(t)}} aria-label="Избранное"><Heart size={18} fill={favorites.includes(t)?'currentColor':'none'}/></button><ArrowRight size={15}/></div></div>})}</div>
      <div className="source-note"><ShieldCheck size={16}/> Данные поступают из публичного API BingX. Котировки могут обновляться с задержкой; сценарии не являются финансовой рекомендацией.</div>
    </>}
    {tab==='terminal'&&<>
      <div className="section-header terminal-head"><div><div className="eyebrow muted">ANALYTICS TERMINAL / V1.0</div><h1>Анализ рынка <span className="heading-dot">.</span></h1><p>11 показателей · многофакторный технический анализ</p></div><button className="outline-btn" onClick={()=>void toggleFavorite(symbol)}><Heart size={16} fill={favorites.includes(symbol)?'currentColor':'none'}/>{favorites.includes(symbol)?'В избранном':'В избранное'}</button></div>
      <div className="instrument-bar"><button className="symbol-select" onClick={()=>setSearchOpen(true)}><CoinLogo symbol={symbol}/><div><strong>{symbol.replace('-',' / ')}</strong><small>BingX Perpetual</small></div><ChevronDown size={17}/></button><div className="instrument-price"><strong>{price(thisTick?.lastPrice)}</strong><span className={thisTick?.change24h>=0?'positive':'negative'}>{thisTick?((thisTick.change24h>=0?'+':'')+thisTick.change24h.toFixed(2)+'%'):'—'}</span></div><div className="instrument-details"><div><small>24H HIGH</small><b>{price(thisTick?.high24h)}</b></div><div><small>24H LOW</small><b>{price(thisTick?.low24h)}</b></div><div><small>24H VOL</small><b>{usd(thisTick?.volume24h)}</b></div></div></div>
      <div className="terminal-grid"><div className="terminal-left"><div className="panel"><div className="panel-top"><div className="panel-heading"><Activity size={18}/> Price action <span> / {symbol}</span></div><div className={'ws-health '+chartStream}>{chartStream==='live'? '● LIVE CANDLES':chartStream==='connecting'?'○ CONNECTING':chartStream==='reconnecting'?'↻ RECONNECTING':'○ REST FALLBACK'}</div><div className="timeframes">{intervals.map(t=><button key={t} className={interval===t?'tf active':'tf'} onClick={()=>{setInterval(t);setResult(null);setArchived(false)}}>{t}</button>)}</div></div>{chartBusy&&!candles.length?<div className="chart-placeholder"><LoaderCircle className="spin"/> Загружаем реальные свечи BingX...</div>:candles.length?<MarketChart key={symbol+'-'+interval} candles={candles} signal={result} light={settings.theme==='light'}/>:<div className="chart-placeholder"><XCircle/>Нет актуальных данных для графика</div>}</div>
        <div className="analysis-action"><div className="action-copy"><div className="action-icon"><Sparkles size={23}/></div><div><strong>Интеллектуальный анализ</strong><span>EMA · RSI · MACD · ATR · объёмы · структура рынка</span></div></div><button className="primary-btn analyze-btn" disabled={busy||!candles.length} onClick={()=>void analyzeNow()}>{busy?<><LoaderCircle size={18} className="spin"/> Анализируем...</>:<><Sparkles size={17}/> Запустить анализ</>}</button></div>
        {archived&&<div className="warning-bar"><Clock size={16}/> Архивный результат. Для актуального сценария нажмите «Запустить анализ».</div>}
        {result&&<motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} className="panel result-panel"><div className="result-heading"><span className="eyebrow muted">РЕЗУЛЬТАТ АНАЛИЗА</span><span className="generated"><Clock size={13}/> {date(result.generatedAt)}</span></div><div className={'signal-hero '+cls(result.side)}><div><span className="signal-caption">ТЕХНИЧЕСКИЙ СЦЕНАРИЙ</span><div className="signal-side">{result.side==='LONG'?<TrendingUp size={26}/>:result.side==='SHORT'?<TrendingDown size={26}/>:<Clock size={26}/>} {result.side}</div><span className="signal-message">{result.side==='WAIT'?'Нет однозначного сценария':result.side==='LONG'?'Преобладают признаки роста':'Преобладают признаки снижения'}</span></div><div className="score"><span>Сила сигналов</span><b>{result.strength}/8</b><small>Не вероятность успеха</small></div></div>
          <p className="signal-summary">{result.summary}</p>{result.aiSummary&&<div className="ai-comment"><Sparkles size={17}/><div><b>AI-комментарий</b><p>{result.aiSummary}</p></div></div>}
          {result.side!=='WAIT'&&<div className="trade-levels"><div className="level-row entry"><span>Entry · ориентир</span><strong>{price(result.entry)}</strong></div><div className="level-grid">{result.takeProfits.map((tp,i)=><div key={i} className="level-tp"><span>TAKE PROFIT {i+1}</span><strong>{price(tp)}</strong></div>)}</div><div className="level-row stop"><span>STOP LOSS · условие отмены</span><strong>{price(result.stopLoss)}</strong></div><div className="risk-row"><span>RISK / REWARD (TP1)</span><b>1 : {result.riskReward?.toFixed(1)}</b></div></div>}
          <div className="reason-head"><Info size={17}/> Почему такой результат?</div><div className="reason-list">{result.reasons.map((r,i)=><div key={i} className="reason-item"><div className={'reason-dot '+cls(r.direction)}/><span>{r.text}</span></div>)}</div>
          <div className="reason-head risk-title"><ShieldCheck size={17}/> Что может пойти не так?</div><div className="risk-list">{result.risks.map((r,i)=><div key={i}>• {r}</div>)}</div>
          <div className="indicator-grid">{[['RSI 14',number(result.metrics.rsi,1)],['MACD',number(result.metrics.macdHistogram,5)],['ATR',price(result.metrics.atr)],['VOL / AVG',number(result.metrics.volumeRatio,2)+'×'],['FUNDING',result.metrics.fundingRate==null?'Н/Д':(result.metrics.fundingRate*100).toFixed(4)+'%'],['OPEN INTEREST',number(result.metrics.openInterest,0)],['BID / ASK',number(result.metrics.bidAskRatio,2)],['EMA 200',price(result.metrics.ema200)]].map(([k,v])=><div className="indicator" key={String(k)}><small>{k}</small><strong>{v}</strong></div>)}</div>
          <div className="result-footer"><ShieldCheck size={16}/> Правила расчёта: rules-v1. Значения основаны на закрытых свечах BingX; будущие движения не гарантированы.</div>
        </motion.div>}
      </div><div className="terminal-right"><div className="panel sidebar-analysis"><div className="panel-heading"><Target size={18}/> Краткий обзор</div><div className="side-metric"><span>Инструмент</span><b>{symbol}</b></div><div className="side-metric"><span>Период</span><b>{interval}</b></div><div className="side-metric"><span>Текущая цена</span><b>{price(thisTick?.lastPrice)}</b></div><div className="side-metric"><span>Поддержка</span><b>{result?.levels?.support?price(result.levels.support):'—'}</b></div><div className="side-metric"><span>Сопротивление</span><b>{result?.levels?.resistance?price(result.levels.resistance):'—'}</b></div><div className="side-metric"><span>Состояние</span><b className="positive">READ ONLY</b></div></div><div className="panel follow-panel"><div className="panel-heading"><BellRing size={17}/> Следить за монетой</div><p>Сообщим в Telegram, когда алгоритм обнаружит новый LONG/SHORT-сценарий.</p><button className={'outline-btn full '+(watching?'watch-active':'')} onClick={()=>void toggleWatch()}>{watching?<><Check size={17}/> Отслеживается</>:<><Plus size={17}/> Добавить слежение</>}</button><small>Проверка примерно раз в 6 минут. Уведомления доступны после /start в боте.</small></div><div className="panel caution-panel"><ShieldCheck size={22}/><b>Только аналитика</b><p>Сигналы не открывают сделки и не дают гарантии доходности. Проверяйте дату, ликвидность и риски.</p></div></div></div>
    </>}
    {tab==='auto'&&<SignalsHub authorized={authorized} favorites={favorites} tickers={tickers} toast={showToast} onOpen={(sig:AutoSignal)=>{setSymbol(sig.symbol);setInterval(sig.interval);setResult(sig.result);setArchived(true);setTab('terminal')}} onOpenSymbol={(sym:string)=>{setSymbol(sym);setInterval('1m');setResult(null);setArchived(false);setTab('terminal')}}/>}
    {tab==='history'&&<><div className="section-header"><div><div className="eyebrow muted">PERSISTENT STORAGE</div><h1>История анализов</h1><p>Реальная статистика сохранённых технических сценариев</p></div><button className="outline-btn" onClick={()=>void loadPrivate()}><RefreshCcw size={16}/> Обновить</button></div>{!authorized?<Locked/>:<><div className="metrics-row history-stats"><div className="stat-card"><div className="stat-label">ДОСТИГНУТ TP1</div><div className="stat-big positive">{stats.TP1||0}</div><div className="stat-sub">Зафиксировано на 1m OHLC</div></div><div className="stat-card"><div className="stat-label">ДОСТИГНУТ SL</div><div className="stat-big negative">{stats.STOP||0}</div><div className="stat-sub">Зафиксировано на 1m OHLC</div></div><div className="stat-card"><div className="stat-label">АКТИВНЫЕ</div><div className="stat-big">{stats.ACTIVE||0}</div><div className="stat-sub">Ждут результата</div></div></div><div className="panel history-panel"><div className="panel-heading">Все анализы <span className="detail-count">{history.length} записей</span></div>{history.length===0?<div className="empty-state"><History size={38}/><b>История пока пуста</b><p>Перейдите в Терминал и запустите первый анализ.</p><button className="outline-btn" onClick={()=>setTab('terminal')}>Перейти в терминал <ArrowRight size={15}/></button></div>:history.map(h=><button key={h.id} className="history-row" onClick={()=>{setSymbol(h.symbol);setInterval(h.interval);setResult(h.result);setArchived(true);setTab('terminal')}}><div className={'history-icon '+cls(h.side)}><CoinLogo symbol={h.symbol} small/></div><div className="history-name"><strong>{h.symbol}</strong><small>{date(h.createdAt)} · {h.interval}</small></div><span className={'side-badge '+cls(h.side)}>{h.side}</span><span className={'status-badge '+h.status.toLowerCase()}>{h.status}</span><ArrowRight size={16}/></button>)}</div><div className="source-note">Если TP и SL достигнуты внутри одной минутной свечи, результат отмечается AMBIGUOUS. Недостающая история отмечается STALE; успешность не дорисовывается.</div></>}</>}
    {tab==='alerts'&&<><div className="section-header"><div><div className="eyebrow muted">SMART NOTIFICATIONS</div><h1>Уведомления</h1><p>Отслеживайте пересечения ценовых уровней и новые технические сценарии</p></div></div>{!authorized?<Locked/>:<div className="alerts-grid"><div className="panel alert-create"><div className="panel-heading"><Plus size={18}/> Новое уведомление</div><form onSubmit={e=>void addAlert(e)}><label>Торговая пара</label><button type="button" className="form-symbol" onClick={()=>setSearchOpen(true)}>{symbol.replace('-',' / ')} <ChevronDown size={15}/></button><label>Цена пересечения (USDT)</label><input type="number" step="any" min="0.00000001" required placeholder={thisTick?.lastPrice?.toString()||'Укажите цену'} value={target} onChange={e=>setTarget(e.target.value)}/><button className="primary-btn full" type="submit"><Bell size={17}/> Создать уведомление</button></form><p className="tiny-info">Уведомление отправляется после первого обнаруженного пересечения. Возможны задержки до нескольких минут.</p></div><div className="panel alert-list"><div className="panel-heading"><BellRing size={18}/> Ценовые уведомления <span className="detail-count">{alerts.filter(x=>x.active).length} активны</span></div>{alerts.length===0?<div className="empty-state"><Bell size={34}/><b>Уведомлений пока нет</b><p>Укажите монету и цену пересечения.</p></div>:alerts.map(a=><div className="alert-row" key={a.id}><span className="alert-icon"><CoinLogo symbol={a.symbol} small/></span><div><strong>{a.symbol}</strong><small>Цель: {price(a.targetPrice)} · {a.active?'Ожидает':'Завершено'}</small></div><button className="circle-btn" aria-label="Удалить" onClick={()=>void removeAlert(a.id)}><Trash2 size={17}/></button></div>)}<div className="panel-heading watches-heading">Отслеживаемые сценарии</div>{watches.length===0?<p className="muted-paragraph">В терминале нажмите «Добавить слежение» для выбранной пары.</p>:watches.map(w=><div className="alert-row" key={w.symbol+w.interval}><span className="alert-icon"><CoinLogo symbol={w.symbol} small/></span><div><strong>{w.symbol} · {w.interval}</strong><small>Последнее направление: {w.lastSide}</small></div><button className="circle-btn" onClick={async()=>{await changeWatch(w.symbol,w.interval,false);setWatches(x=>x.filter(z=>z.symbol!==w.symbol||z.interval!==w.interval))}}><Trash2 size={17}/></button></div>)}</div></div>}</>}
    {tab==='settings'&&<><div className="section-header"><div><div className="eyebrow muted">PREFERENCES</div><h1>Настройки</h1><p>Персонализация терминала и уведомлений</p></div></div><div className="settings-grid"><div className="panel preferences"><div className="panel-heading"><SlidersHorizontal size={18}/> Предпочтения</div><div className="setting-row"><div><b>Тема интерфейса</b><small>Тёмная или светлая</small></div><div className="segment"><button className={settings.theme==='dark'?'selected':''} onClick={()=>void patchSettings({theme:'dark'})}>Тёмная</button><button className={settings.theme==='light'?'selected':''} onClick={()=>void patchSettings({theme:'light'})}>Светлая</button></div></div><div className="setting-row"><div><b>Язык</b><small>Язык уведомлений и интерфейса</small></div><div className="segment"><button className={settings.language==='ru'?'selected':''} onClick={()=>void patchSettings({language:'ru'})}>RU</button><button className={settings.language==='en'?'selected':''} onClick={()=>void patchSettings({language:'en'})}>EN</button></div></div><div className="setting-row"><div><b>Таймфрейм по умолчанию</b><small>Применяется при открытии терминала</small></div><select value={settings.interval} onChange={e=>void patchSettings({interval:e.target.value as Timeframe})}>{intervals.map(t=><option key={t}>{t}</option>)}</select></div><div className="setting-row"><div><b>Telegram-уведомления</b><small>Цены и новые сценарии</small></div><button className={'toggle '+(settings.notifications?'enabled':'')} onClick={()=>void patchSettings({notifications:!settings.notifications})} aria-label="Переключить уведомления"><span/></button></div></div><div className="panel account-panel"><div className="panel-heading"><ShieldCheck size={18}/> Подключение</div><div className="account-status"><div className="account-mark">{authorized?<Check size={22}/>:<LockKeyhole size={22}/>}</div><div><strong>{authorized?'Telegram подключён':'Гостевой режим'}</strong><small>{authorized?`Telegram ID: ${settings.userId}`:'Откройте через Telegram для персональных функций'}</small></div></div><div className="side-metric"><span>Уведомления в чате</span><b>{settings.chatConnected?'Подключены':'Требуется /start'}</b></div><div className="side-metric"><span>Торговые операции</span><b className="positive">Отключены</b></div><div className="side-metric"><span>Источники</span><b>BingX Public API</b></div></div></div><div className="source-note"><Info size={16}/> Переключение языка сохраняется в настройках аккаунта; основной текст интерфейса в данной версии доступен на русском.</div></>}
    </motion.div></AnimatePresence>
   </div>
  </main>
  <nav className="bottom-nav">{tabs.map(t=><button key={t.id} className={tab===t.id?'active':''} onClick={()=>setTab(t.id)}><t.icon size={21}/><span>{t.label}</span></button>)}</nav>
  <AnimatePresence>{searchOpen&&<motion.div className="modal-backdrop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} onClick={()=>setSearchOpen(false)}><motion.div className="search-modal" initial={{y:20,scale:.97}} animate={{y:0,scale:1}} exit={{y:10,opacity:0}} onClick={e=>e.stopPropagation()}><div className="search-modal-head"><strong>Выбрать криптовалюту</strong><button className="circle-btn" onClick={()=>setSearchOpen(false)}><X size={18}/></button></div><div className="search-modal-input"><Search size={20}/><input autoFocus placeholder="Начните вводить, например BTC..." value={search} onChange={e=>setSearch(e.target.value)}/></div><div className="search-results">{filtered.slice(0,50).map(s=><button key={s} onClick={()=>choose(s)}><CoinLogo symbol={s} small/><div><strong>{s.replace('-',' / ')}</strong><small>BingX Perpetual</small></div><span>{price(tickMap[s]?.lastPrice)}</span><ArrowRight size={15}/></button>)}{filtered.length===0&&<div className="empty-text">Пары не найдены</div>}</div></motion.div></motion.div>}</AnimatePresence>
  <AnimatePresence>{toast&&<motion.div className="toast" initial={{opacity:0,y:15}} animate={{opacity:1,y:0}} exit={{opacity:0,y:12}}><Info size={16}/>{toast}<button onClick={()=>setToast('')}><X size={14}/></button></motion.div>}</AnimatePresence>
  {error&&tab==='home'&&<div className="error-banner"><Wifi size={16}/> {error} <button onClick={()=>void loadMarket()}>Повторить</button></div>}
 </div>
}

function Locked(){return <div className="panel locked"><LockKeyhole size={38}/><h3>Доступно в Telegram Mini App</h3><p>Откройте приложение через кнопку в Telegram-боте. Авторизация Telegram защищает вашу историю, избранное и уведомления.</p><span className="secure-badge"><ShieldCheck size={15}/> Без паролей и торговых ключей</span></div>}

createRoot(document.getElementById('root')!).render(<React.StrictMode><CoinLogoProvider><App/></CoinLogoProvider></React.StrictMode>)
