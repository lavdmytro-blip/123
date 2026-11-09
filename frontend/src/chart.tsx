import {useEffect,useRef,useState} from 'react'
import {CandlestickSeries,LineSeries,HistogramSeries,createChart,ColorType,type IPriceLine,type ISeriesApi} from 'lightweight-charts'
import {BarChart3,Layers3} from 'lucide-react'
import type {Candle,Signal} from './types'

function ema(candles:Candle[],period:number){let last=candles[0]?.close||0;const alpha=2/(period+1);return candles.map((c)=>{last=c.close*alpha+last*(1-alpha);return {time:Math.floor(c.time/1000) as any,value:last}})}
const ohlc=(c:Candle)=>({time:Math.floor(c.time/1000) as any,open:c.open,high:c.high,low:c.low,close:c.close})
const volBar=(c:Candle)=>({time:Math.floor(c.time/1000) as any,value:c.volume,color:c.close>=c.open?'#29d59b29':'#f36d8829'})

/** Chart instance remains mounted as the current candle changes; no fitContent on every tick. */
export function MarketChart({candles,signal,light=false}:{candles:Candle[],signal:Signal|null,light?:boolean}){
 const host=useRef<HTMLDivElement>(null)
 const candleRef=useRef<ISeriesApi<'Candlestick'>|null>(null)
 const volumeRef=useRef<ISeriesApi<'Histogram'>|null>(null)
 const emaRefs=useRef<Array<ISeriesApi<'Line'>>>([])
 const lastTime=useRef<number|null>(null)
 const firstTime=useRef<number|null>(null)
 const [indicators,setIndicators]=useState(true)
 const [volume,setVolume]=useState(true)
 useEffect(()=>{
  const target=host.current
  if(!target)return
  const chart=createChart(target,{
    width:target.clientWidth,height:390,
    layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#10131f'},textColor:light?'#727b94':'#838aa6',fontSize:11},
    grid:{vertLines:{color:light?'#e9edf5':'#1c2030'},horzLines:{color:light?'#e9edf5':'#1c2030'}},
    rightPriceScale:{borderColor:light?'#e2e6ef':'#272c3f'},timeScale:{borderColor:light?'#e2e6ef':'#272c3f',timeVisible:true,secondsVisible:false},
    crosshair:{vertLine:{color:'#7777bd'},horzLine:{color:'#7777bd'}}
  })
  candleRef.current=chart.addSeries(CandlestickSeries,{upColor:'#29d59b',downColor:'#f36d88',borderVisible:false,wickUpColor:'#29d59b',wickDownColor:'#f36d88'})
  if(volume){volumeRef.current=chart.addSeries(HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'volume',lastValueVisible:false,priceLineVisible:false});chart.priceScale('volume').applyOptions({scaleMargins:{top:0.83,bottom:0}})}
  if(indicators){for(const [n,color] of [[20,'#8868ff'],[50,'#e4b86a'],[200,'#459fee']] as const){emaRefs.current.push(chart.addSeries(LineSeries,{color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,title:'EMA'+n}))}}
  // Initial setData is performed here, because the series exist before the next effect runs.
  const rows=candles.filter(x=>x.time>0)
  if(rows.length){candleRef.current.setData(rows.map(ohlc));volumeRef.current?.setData(rows.map(volBar));emaRefs.current.forEach((series,i)=>series.setData(ema(rows,[20,50,200][i])));lastTime.current=rows.at(-1)!.time;firstTime.current=rows[0].time;chart.timeScale().fitContent()}
  const ro=new ResizeObserver(()=>chart.applyOptions({width:target.clientWidth}))
  ro.observe(target)
  return()=>{ro.disconnect();chart.remove();candleRef.current=null;volumeRef.current=null;emaRefs.current=[];lastTime.current=null;firstTime.current=null}
 },[light,indicators,volume]) // deliberately not candles or signal: no chart recreation per update
 useEffect(()=>{
   const c=candleRef.current
   if(!c||!candles.length)return
   const current=candles.at(-1)!
   const needsFull=lastTime.current===null || firstTime.current===null ||
      candles[0].time < firstTime.current || current.time < lastTime.current ||
      (current.time-lastTime.current > 3*86400000)
   if(needsFull){
     c.setData(candles.map(ohlc));volumeRef.current?.setData(candles.map(volBar));
     emaRefs.current.forEach((series,i)=>series.setData(ema(candles,[20,50,200][i])))
   }else{
     // update() changes just the last bar, retaining zoom/scroll and original chart.
     c.update(ohlc(current));volumeRef.current?.update(volBar(current));
     emaRefs.current.forEach((series,i)=>series.update(ema(candles,[20,50,200][i]).at(-1)!))
   }
   lastTime.current=current.time;firstTime.current=candles[0].time
 },[candles])
 useEffect(()=>{
   const c=candleRef.current
   if(!c||!signal||signal.side==='WAIT'||!signal.entry||!signal.stopLoss)return
   const lines:IPriceLine[]=[]
   const add=(p:number,color:string,title:string)=>lines.push(c.createPriceLine({price:p,color,lineWidth:2,lineStyle:2,axisLabelVisible:true,title}))
   add(signal.entry,'#a2abce','ENTRY');add(signal.stopLoss,'#f36d88','STOP');signal.takeProfits.forEach((p,i)=>add(p,'#29d59b','TP'+(i+1)))
   return()=>lines.forEach(l=>c.removePriceLine(l))
 },[signal,light,indicators,volume])
 return <div className="chart-wrap"><div className="chart-bar"><span className="chart-label"><BarChart3 size={15}/> Свечной график · BingX</span><div className="chart-switches"><button className={indicators?'chip on':'chip'} onClick={()=>setIndicators(!indicators)} title="EMA 20/50/200"><Layers3 size={13}/> EMA</button><button className={volume?'chip on':'chip'} onClick={()=>setVolume(!volume)} title="Объём">VOL</button></div></div><div ref={host} className="chart-host"/></div>
}

export function Sparkline({values,positive}:{values:number[],positive:boolean}){
 if(values.length<3)return <span className="spark-empty">—</span>
 const min=Math.min(...values),max=Math.max(...values),d=max-min||1
 const path=values.map((n,i)=>`${i?'L':'M'} ${(i/(values.length-1)*118).toFixed(1)} ${(35-((n-min)/d*31)).toFixed(1)}`).join(' ')
 return <svg aria-hidden="true" className="sparkline" viewBox="0 0 120 40"><path d={path} stroke={positive?'#2dd6a0':'#f26b8a'} fill="none" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
}
