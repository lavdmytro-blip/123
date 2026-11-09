import {useState} from 'react'
import {Flame,Sparkles} from 'lucide-react'
import {AutoFeed} from './AutoFeed'
import {PumpFeed} from './PumpFeed'
import type {AutoSignal,Ticker} from './types'

export function SignalsHub(props:{authorized:boolean;favorites:string[];tickers:Ticker[];onOpen:(sig:AutoSignal)=>void;onOpenSymbol:(sym:string)=>void;toast:(s:string)=>void}){
  const [mode,setMode]=useState<'auto'|'pump'>('auto')
  return <>
    <div className="signal-hub-tabs"><button className={mode==='auto'?'selected':''} onClick={()=>setMode('auto')}><Sparkles size={17}/> AI Сигналы</button><button className={mode==='pump'?'selected pump-selected':''} onClick={()=>setMode('pump')}><Flame size={17}/> PUMP / DUMP</button></div>
    {mode==='auto'?<AutoFeed authorized={props.authorized} favorites={props.favorites} tickers={props.tickers} onOpen={props.onOpen} toast={props.toast}/>:<PumpFeed authorized={props.authorized} tickers={props.tickers} onOpen={props.onOpenSymbol} toast={props.toast}/>}
  </>
}
