import {useCallback,useEffect,useState} from 'react'
import {Activity,ArrowRight,CalendarDays,CheckCircle2,Clock3,History,Info,LoaderCircle,RefreshCcw,Search,ShieldCheck,TrendingDown,TrendingUp,XCircle} from 'lucide-react'
import {getAutoHistory} from './api'
import {CoinLogo} from './CoinLogo'
import type {ArchivedAutoSignal,AutoHistoryResponse,HistoryOutcome} from './types'

const money=(value:number | null | undefined)=>value==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:Math.abs(value)>=10?3:8}).format(value)
const stamp=(value:string|null)=>value?new Date(value).toLocaleString('ru-RU',{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'Не сохранено'
const statusLabel:Record<string,string>={ACTIVE:'В работе',STOP:'STOP LOSS',TP3:'TP3 достигнут',STALE:'Недостаточно данных',AMBIGUOUS:'TP и SL в одной свече',EXPIRED:'Время истекло'}
const statusClass=(status:string)=>status==='TP3'?'positive':status==='STOP'?'negative':'neutral'
const outcomes:{value:HistoryOutcome,label:string}[]=[
 {value:'COMPLETED',label:'Завершённые'}, {value:'ALL',label:'Все'},
 {value:'TP3',label:'TP3'}, {value:'STOP',label:'STOP'},
 {value:'AMBIGUOUS',label:'Неоднозначные'}, {value:'STALE',label:'STALE'},
 {value:'EXPIRED',label:'Истёкшие'}, {value:'ACTIVE',label:'Активные'}]

export function TradeHistory({onOpen,onPersonal}: {onOpen:(s:ArchivedAutoSignal)=>void;onPersonal:()=>void}){
 const [data,setData]=useState<AutoHistoryResponse|null>(null)
 const [loading,setLoading]=useState(true)
 const [error,setError]=useState('')
 const [page,setPage]=useState(1)
 const [outcome,setOutcome]=useState<HistoryOutcome>('COMPLETED')
 const [side,setSide]=useState<'ALL'|'LONG'|'SHORT'>('ALL')
 const [search,setSearch]=useState('')
 const [query,setQuery]=useState('')
 const [from,setFrom]=useState('')
 const [to,setTo]=useState('')
 const [revision,setRevision]=useState(0)
 useEffect(()=>{const t=window.setTimeout(()=>setQuery(search.trim()),350);return()=>window.clearTimeout(t)},[search])
 useEffect(()=>{setPage(1)},[query,outcome,side,from,to])
 const load=useCallback(async()=>{
   return getAutoHistory({page,pageSize:20,outcome,side,symbol:query,dateFrom:from,dateTo:to})
 },[page,outcome,side,query,from,to])
 useEffect(()=>{
   let live=true
   setLoading(true)
   load().then(x=>{if(live){setData(x);setError('')}}).catch((e:Error)=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)})
   const timer=window.setInterval(()=>{load().then(x=>{if(live){setData(x);setError('')}}).catch(()=>{})},45000)
   return()=>{live=false;window.clearInterval(timer)}
 },[load,revision])
 const stats=data?.stats
 return <>
   <div className="section-header"><div><div className="eyebrow muted">AUTO SIGNALS / ARCHIVE</div><h1>История сделок <span className="heading-dot">.</span></h1><p>История виртуальных сценариев бота из PostgreSQL, включая старые и исключённые из текущего фильтра монеты.</p></div>
     <div className="trade-archive-top-actions"><button className="outline-btn" onClick={onPersonal}><History size={16}/> Мои анализы</button><button className="outline-btn" onClick={()=>setRevision(x=>x+1)}><RefreshCcw size={16}/> Обновить</button></div>
   </div>
   <div className="trade-archive-stats">
     <div className="panel trade-archive-stat"><small>ВСЕГО СИГНАЛОВ</small><strong>{stats?.total??'—'}</strong><span>В сохранённой базе</span></div>
     <div className="panel trade-archive-stat"><small>TP3 ДОСТИГНУТ</small><strong className="positive">{stats?.tp3??'—'}</strong><span>Полностью достигнутая цель</span></div>
     <div className="panel trade-archive-stat"><small>STOP LOSS</small><strong className="negative">{stats?.stop??'—'}</strong><span>Достигнут уровень стопа</span></div>
     <div className="panel trade-archive-stat"><small>TP3 / ИЗВЕСТНЫЕ ИСХОДЫ</small><strong>{stats?.tp3ShareOfKnownPercent==null?'—':`${stats.tp3ShareOfKnownPercent}%`}</strong><span>Только TP3 и STOP; не доходность</span></div>
   </div>
   <div className="panel trade-extra-stats"><span><CheckCircle2 size={15}/> TP1 достигнут: <b>{stats?.tp1Reached??'—'}</b></span><span>TP2: <b>{stats?.tp2Reached??'—'}</b></span><span>Активные: <b>{stats?.active??'—'}</b></span><span>Неоднозначные: <b>{stats?.ambiguous??'—'}</b></span><span>STALE/EXPIRED: <b>{stats?(stats.stale+stats.expired):'—'}</b></span></div>
   <div className="panel trade-archive-filters">
    <div className="trade-filter-row">
     <label>Результат<select value={outcome} onChange={e=>setOutcome(e.target.value as HistoryOutcome)}>{outcomes.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
     <label>Направление<select value={side} onChange={e=>setSide(e.target.value as typeof side)}><option value="ALL">LONG и SHORT</option><option value="LONG">LONG</option><option value="SHORT">SHORT</option></select></label>
     <label className="trade-filter-search">Монета <span><Search size={15}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="BTC, SOL, ETH…" maxLength={30}/></span></label>
    </div>
    <div className="trade-filter-row"><label><CalendarDays size={14}/> С даты<input type="date" value={from} max={to||undefined} onChange={e=>setFrom(e.target.value)}/></label><label><CalendarDays size={14}/> По дату<input type="date" value={to} min={from||undefined} onChange={e=>setTo(e.target.value)}/></label>
      <span className="trade-found">Найдено: <b>{data?.total??'—'}</b></span></div>
   </div>
   {loading&&<div className="panel auto-empty"><LoaderCircle className="spin" size={28}/> Загружаем сохранённые сигналы…</div>}
   {!loading&&error&&<div className="panel auto-empty"><XCircle size={28}/><b>Не удалось загрузить историю</b><p>{error}</p><button className="outline-btn" onClick={()=>setRevision(x=>x+1)}>Повторить</button></div>}
   {!loading&&!error&&data?.items.length===0&&<div className="panel auto-empty"><History size={33}/><b>По выбранным фильтрам записей пока нет</b><p>Проверь «Все» или очисти поиск. Сигналы появляются только после создания автосценариев сканером; старые данные не создаются задним числом.</p></div>}
   {!loading&&!error&&<div className="trade-archive-list">{data?.items.map(item=><TradeHistoryCard key={item.id} item={item} onOpen={()=>onOpen(item)}/>)}</div>}
   {!loading&&!error&&!!data?.total&&<div className="trade-pagination"><button className="outline-btn" disabled={page<=1} onClick={()=>setPage(x=>Math.max(1,x-1))}>Назад</button><span>Страница {page} из {Math.max(1,Math.ceil(data.total/data.pageSize))}</span><button className="outline-btn" disabled={!data.hasMore} onClick={()=>setPage(x=>x+1)}>Вперёд <ArrowRight size={15}/></button></div>}
   <div className="source-note trade-archive-note"><ShieldCheck size={17}/> Это архив виртуальных аналитических сигналов, а не реальные сделки. Статусы рассчитаны по минутным свечам; частичная фиксация TP, комиссии, плечо и проскальзывание не моделируются. Доля TP3 среди определённых исходов не является прогнозом успешности.</div>
 </>
}

function TradeHistoryCard({item,onOpen}:{item:ArchivedAutoSignal;onOpen:()=>void}){
 const cls=statusClass(item.status)
 const closed=item.finishedAtSource==='last_checked_candle'?'По последней проверенной свече':item.finishedAtSource==='recorded'?'Время фиксации':'Время завершения не сохранилось'
 return <div className="panel trade-archive-card">
  <div className="trade-archive-head"><CoinLogo symbol={item.symbol}/><div className="trade-archive-symbol"><b>{item.symbol.replace('-',' / ')}</b><small>#{item.id} · {item.interval} · <span className={item.side==='LONG'?'positive':'negative'}>{item.side==='LONG'?<TrendingUp size={12}/>:<TrendingDown size={12}/>} {item.side}</span></small></div><span className={'trade-archive-status '+cls}>{statusLabel[item.status]??item.status}</span></div>
  <div className="trade-archive-dates"><span><Clock3 size={14}/> Создан: {stamp(item.createdAt)}</span><span><CheckCircle2 size={14}/> Завершён: {stamp(item.finishedAt)} <small>· {closed}</small></span></div>
  <div className="trade-archive-levels"><div><small>ENTRY</small><b>{money(item.entry)}</b></div><div><small>STOP LOSS</small><b className="negative">{money(item.stopLoss)}</b></div>{item.takeProfits.map((tp,i)=><div key={i}><small>{i+1<=item.tpReached?'✓ ':''}TP{i+1}</small><b className={i+1<=item.tpReached?'positive':''}>{money(tp)}</b></div>)}</div>
  <div className="trade-archive-footer"><div><Activity size={15}/>{item.terminalMovePercent!=null?<span>Движение от входа до {item.status==='TP3'?'TP3':'SL'}: <b className={item.terminalMovePercent>=0?'positive':'negative'}>{item.terminalMovePercent>0?'+':''}{item.terminalMovePercent.toFixed(2)}%</b> <small>· условно, без комиссий</small></span>:<span>Итог нельзя достоверно рассчитать · достигнуто TP: {item.tpReached}</span>}</div><button className="outline-btn" onClick={onOpen}>График <ArrowRight size={15}/></button></div>
  {item.status==='AMBIGUOUS'&&<p className="trade-archive-caution"><Info size={14}/> Цена затронула TP и SL в одной минутной свече — последовательность неизвестна.</p>}
 </div>
}
