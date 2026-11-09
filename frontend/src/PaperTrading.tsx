import {useCallback,useEffect,useMemo,useState} from 'react'
import {Activity,AlertCircle,Clock,Coins,ExternalLink,Info,Pause,Play,RefreshCcw,RotateCcw,ShieldCheck,Wallet} from 'lucide-react'
import {closePaperPosition,getAutoFeed,getPaperAccount,resetPaper,setPaperEnabled} from './api'
import {CoinLogo} from './CoinLogo'
import type {AutoFeedResponse,PaperAccountResponse,PaperPosition} from './types'

const money=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'—':new Intl.NumberFormat('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}).format(v)
const rate=(v:number)=>new Intl.NumberFormat('en-US',{maximumSignificantDigits:8}).format(v)
const time=(v:string)=>new Date(v).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})
const statusLabel=(s:string)=>({OPEN:'В работе',TP3:'Все TP',STOP:'Стоп',AMBIGUOUS:'TP/SL в одной свече',DATA_GAP:'Пробел в данных',EXPIRED:'Истёк срок',MANUAL:'Закрыта вручную'} as Record<string,string>)[s]||s

export function PaperTrading({authorized,onOpen}:{authorized:boolean;onOpen:(symbol:string)=>void}){
 const [data,setData]=useState<PaperAccountResponse|null>(null)
 const [autoFeed,setAutoFeed]=useState<AutoFeedResponse|null>(null)
 const [scanError,setScanError]=useState('')
 const [loading,setLoading]=useState(true)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 const [view,setView]=useState<'open'|'closed'>('open')
 const reload=useCallback(async()=>{
  // Scanner diagnostics are independent: a public-market outage must not hide the personal ledger.
  const [accountResult,scanResult]=await Promise.allSettled([getPaperAccount(),getAutoFeed()])
  if(accountResult.status==='fulfilled'){setData(accountResult.value);setError('')}
  else setError((accountResult.reason as Error)?.message||'Не удалось загрузить демо-счёт')
  if(scanResult.status==='fulfilled'){setAutoFeed(scanResult.value);setScanError('')}
  else setScanError((scanResult.reason as Error)?.message||'Сканер недоступен')
  setLoading(false)
 },[])
 useEffect(()=>{if(!authorized){setLoading(false);return}
  void reload();const timer=window.setInterval(()=>void reload(),20000)
  return()=>window.clearInterval(timer)
 },[authorized,reload])
 const active=useMemo(()=>data?.positions.filter(p=>p.status==='OPEN'||p.status==='DATA_GAP')||[],[data])
 const closed=useMemo(()=>data?.positions.filter(p=>p.status!=='OPEN'&&p.status!=='DATA_GAP')||[],[data])
 async function toggle(){if(!data)return
  if(!data.enabled&&!window.confirm('Включить автоматическую ДЕМО-торговлю? Бот будет открывать только виртуальные позиции по НОВЫМ сигналам. Реальные ордера не создаются.'))return
  setBusy(true);try{await setPaperEnabled(!data.enabled);await reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function close(position:PaperPosition){if(!window.confirm(`Виртуально закрыть ${position.symbol} по текущей котировке?`))return
  setBusy(true);try{await closePaperPosition(position.id);await reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 async function reset(){if(!window.confirm('Удалить ВСЮ историю демо-позиций и восстановить 1 000 виртуальных USDT? Действие нельзя отменить.'))return
  setBusy(true);try{await resetPaper();await reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 if(!authorized)return <div className="paper-screen"><div className="section-header"><div><div className="eyebrow muted">PAPER PORTFOLIO</div><h1>Демо-торговля</h1></div></div><div className="panel paper-intro"><ShieldCheck size={30}/><h2>Открой Mini App через своего Telegram-бота</h2><p>Для виртуального баланса и персональной истории нужна авторизация Telegram.</p></div></div>
 if(!data)return <div className="paper-screen"><div className="section-header"><div><div className="eyebrow muted">VIRTUAL ONLY</div><h1>Демо-торговля</h1></div></div><div className="panel paper-intro"><AlertCircle size={28}/><h2>{loading?'Загружаем демо-счёт...':'Не удалось загрузить демо-счёт'}</h2><p>{error||'Обновляем данные сервера'}</p><button className="outline-btn" onClick={()=>void reload()}><RefreshCcw size={16}/> Повторить</button></div></div>
 return <div className="paper-screen">
  <div className="section-header"><div><div className="eyebrow muted">VIRTUAL ONLY / 1× / NO EXCHANGE ORDERS</div><h1>Демо-торговля</h1><p>Автоматическое моделирование сделок по новым AI-сигналам. Реальные деньги не используются.</p></div><button className="outline-btn" onClick={()=>void reload()} disabled={busy}><RefreshCcw size={15}/> Обновить</button></div>
  {error&&<div className="paper-error"><AlertCircle size={16}/> {error}</div>}
  <>
  <div className="paper-summary">
   <div className="stat-card"><div className="stat-label"><Wallet size={15}/> ВИРТУАЛЬНЫЙ БАЛАНС</div><div className="stat-big">{money(data?.equity)} <small>USDT</small></div><div className="stat-sub">{data?.equity==null?'Нет актуальных цен для оценки':`Старт: ${money(data?.initialBalance)} USDT · включая незакрытые позиции`}</div></div>
   <div className="stat-card"><div className="stat-label"><Coins size={15}/> СВОБОДНЫЕ СРЕДСТВА</div><div className="stat-big">{money(data?.cash)} <small>USDT</small></div><div className="stat-sub">Остальное зарезервировано в виртуальных позициях</div></div>
   <div className="stat-card"><div className="stat-label"><Activity size={15}/> ВИРТУАЛЬНЫЙ РЕЗУЛЬТАТ</div><div className={'stat-big '+((data?.stats.netPnl||0)>=0?'positive':'negative')}>{(data?.stats.netPnl||0)>=0?'+':''}{money(data?.stats.netPnl)} <small>USDT</small></div><div className="stat-sub">Закрытых: {data?.stats.closed||0} · положительных: {data?.stats.win||0}</div></div>
  </div>
  <div className="panel paper-settings"><div className="paper-settings-head"><div><h2><ShieldCheck size={20}/> Автоматическая демо-торговля</h2><p>Открываются только НОВЫЕ сигналы, прошедшие фильтр Balanced (возраст пары от 30 дней, оборот от 10 млн USDT).</p></div><span className={'paper-state '+(data?.enabled?'on':'off')}>{data?.enabled?'ВКЛЮЧЕНО':'ВЫКЛЮЧЕНО'}</span></div>
   <div className="paper-rules"><span>Максимум 2 позиции</span><span>Без плеча (1×)</span><span>До 20% свободного баланса на вход</span><span>Модельный риск до 1%</span><span>Комиссия 0.05% / сторона</span><span>Проскальзывание 0.05%</span></div>
   <div className="paper-actions"><button className={data?.enabled?'outline-btn':'primary-btn'} onClick={()=>void toggle()} disabled={busy}>{data?.enabled?<><Pause size={16}/> Отключить новые входы</>:<><Play size={16}/> Включить демо-торговлю</>}</button>
    <button className="outline-btn" disabled={busy||data?.enabled||active.length>0} onClick={()=>void reset()}><RotateCcw size={15}/> Сбросить демо-счёт</button></div>
   <p className="tiny-info">Выключение останавливает только новые виртуальные входы. Уже открытые позиции продолжают отслеживаться. Сброс удаляет историю и возможен только после выключения и закрытия всех позиций.</p>
  </div>
  <div className="panel paper-diagnostics">
   <div className="paper-settings-head"><div><h2><Activity size={19}/> Почему нет демо-позиций?</h2><p>Демо-счёт не открывает позицию при включении. Он ждёт НОВЫЙ автосигнал, который прошёл проверки.</p></div><button className="outline-btn" onClick={()=>void reload()} disabled={busy}><RefreshCcw size={15}/> Проверить</button></div>
   <div className="paper-diag-grid">
    <div><small>Демо-счёт</small><strong>{data.enabled?'Включён':'Выключен'}</strong></div>
    <div><small>Автосканер</small><strong>{!autoFeed?'Неизвестно':autoFeed.scannerEnabled?'Включён':'Выключен'}</strong></div>
    <div><small>Допущено пар</small><strong>{autoFeed?.marketFilter?.eligible??'—'}</strong></div>
    <div><small>Проверено за проход</small><strong>{autoFeed?`${autoFeed.scanner.scanned} / ${autoFeed.scanner.total}`:'—'}</strong></div>
    <div><small>Сценариев в текущей ленте</small><strong>{autoFeed?.signals.length??'—'}</strong></div>
    <div><small>Время последнего сканирования</small><strong>{autoFeed?.scanner.lastUpdate?time(autoFeed.scanner.lastUpdate):'—'}</strong></div>
   </div>
   <p className="paper-diag-hint">{
    !data.enabled?'Сначала нажми «Включить демо-торговлю» выше.':
    scanError?'Не удалось получить статус сканера: '+scanError:
    !autoFeed?'Загружаем состояние автосканера.':
    !autoFeed.scannerEnabled?'Фоновый сканер выключен. Проверь Railway Variables: ENABLE_WORKER=true и AUTO_SIGNALS_ENABLED=true.':
    autoFeed.scanner.error?'Ошибка сканера: '+autoFeed.scanner.error:
    (autoFeed.marketFilter?.eligible===0)?'Фильтр не допустил ни одной пары. Проверь /api/market-filter, особенно возраст листинга и quoteVolume.':
    !autoFeed.scanner.lastUpdate?'Сканер ещё не начал первый проход или серверный worker не запущен.':
    Date.now()-new Date(autoFeed.scanner.lastUpdate).getTime()>10*60_000?'Сканер давно не обновлялся: проверь Deploy Logs в Railway.':
    autoFeed.signals.length===0?'В ленте ещё нет подходящих автосигналов. Условия анализа строгие — это не ошибка самого демо-счёта.':
    data.stats.active===0?'В общей ленте уже есть сигналы, но демо учитывает только новые публикации после включения. Если новые сигналы появляются, а позиция нет — проверь Deploy Logs.':
    'Автоматический демо-мониторинг активен.'
   }</p>
   <p className="tiny-info">Значения обновляются по кнопке или каждые 20 секунд. Сигналы, появившиеся до включения демо, не открываются задним числом. Здесь не создаются тестовые или реальные ордера.</p>
  </div>
  <div className="section-header"><div><h2>Позиции и отработка</h2><p>По закрытым 1-минутным свечам BingX, без реального исполнения ордеров</p></div><div className="segment"><button className={view==='open'?'selected':''} onClick={()=>setView('open')}>Активные ({active.length})</button><button className={view==='closed'?'selected':''} onClick={()=>setView('closed')}>История ({closed.length})</button></div></div>
  {(view==='open'?active:closed).length===0?<div className="panel paper-empty"><Clock size={32}/><h3>{view==='open'?'Открытых демо-позиций нет':'История пока пуста'}</h3><p>{view==='open'?'Включи демо-режим: при появлении следующего подходящего автосигнала бот смоделирует вход.':'Здесь будут результаты виртуального закрытия по TP, SL, истечению срока или вручную.'}</p></div>
  :<div className="paper-list">{(view==='open'?active:closed).map(p=><PositionCard key={p.id} p={p} busy={busy} onOpen={onOpen} onClose={()=>void close(p)}/>)}</div>}
  <div className="source-note paper-disclaimer"><Info size={16}/> Все суммы условные. P&L моделируется по котировкам и минутным OHLC, без funding и налогов. В одной свече порядок TP/SL неизвестен — используется консервативный стоп, результат отмечается AMBIGUOUS. Если истории не хватает, позиция замораживается; возможен ручной демо-выход по свежей цене.</div>
  </>
 </div>
}

function PositionCard({p,busy,onOpen,onClose}:{p:PaperPosition;busy:boolean;onOpen:(s:string)=>void;onClose:()=>void}){
 const isActive=p.status==='OPEN'||p.status==='DATA_GAP'
 return <div className="panel paper-position">
  <div className="paper-position-head"><div className="paper-pair"><CoinLogo symbol={p.symbol}/><div><strong>{p.symbol.replace('-',' / ')}</strong><small>Сигнал #{p.signalId} · {time(p.createdAt)}</small></div></div><div className="paper-badges"><span className={'side-badge '+(p.side==='LONG'?'long':'short')}>{p.side}</span><span className={'paper-state '+(isActive?'on':'off')}>{statusLabel(p.status)}</span></div></div>
  <div className="paper-position-grid"><div><small>Вход (с проскальзыванием)</small><b>${rate(p.entryFill)}</b></div><div><small>Сейчас</small><b>{p.lastPrice?'$'+rate(p.lastPrice):'—'}</b></div><div><small>Реализованный P&L</small><b className={p.realizedPnl>=0?'positive':'negative'}>{p.realizedPnl>=0?'+':''}{money(p.realizedPnl)} USDT</b></div><div><small>Открытый P&L</small><b className={(p.unrealizedPnl||0)>=0?'positive':'negative'}>{p.unrealizedPnl==null?'—':(p.unrealizedPnl>=0?'+':'')+money(p.unrealizedPnl)+' USDT'}</b></div></div>
  <div className="paper-levels"><span>SL: <b>${rate(p.stop)}</b></span>{p.takeProfits.map((tp,i)=><span key={i} className={p.tpReached>i?'positive':''}>TP{i+1}: <b>${rate(tp)}</b>{p.tpReached>i?' ✓':''}</span>)}</div>
  {p.fills.length>0&&<div className="paper-fills">{p.fills.map((f,i)=><div key={i}><span>{f.reason}</span><span>{rate(f.quantity)} × ${rate(f.fillPrice)}</span><b className={f.pnl>=0?'positive':'negative'}>{f.pnl>=0?'+':''}{money(f.pnl)} USDT</b></div>)}</div>}
  <div className="paper-position-foot"><span><Clock size={13}/> {p.finishedAt?'Закрыто: '+time(p.finishedAt):p.status==='DATA_GAP'?'Требуется ручная проверка':'Отслеживание активно'} · Комиссии: {money(p.fees)} USDT</span><div><button className="outline-btn" onClick={()=>onOpen(p.symbol)}>График <ExternalLink size={14}/></button>{isActive&&<button className="outline-btn" onClick={onClose} disabled={busy}>Демо-закрытие</button>}</div></div>
 </div>
}
