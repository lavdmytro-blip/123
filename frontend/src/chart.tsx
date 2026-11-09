import {useEffect,useRef,useState} from 'react'
import {CandlestickSeries, LineSeries, HistogramSeries,createChart,ColorType,type IPriceLine} from 'lightweight-charts'
import {BarChart3,Layers3} from 'lucide-react'
import type {Candle,Signal} from './types'

function ema(candles:Candle[],period:number){let last=candles[0]?.close||0;const alpha=2/(period+1);return candles.map((c)=>{last=c.close*alpha+last*(1-alpha);return {time:Math.floor(c.time/1000) as any,value:last}})}

export function MarketChart({candles,signal,light=false}:{candles:Candle[],signal:Signal|null,light?:boolean}){
 const host=useRef<HTMLDivElement>(null)
 const [indicators,setIndicators]=useState(true)
 const [volume,setVolume]=useState(true)
 useEffect(()=>{
  const target=host.current
  if(!target||!candles.length)return
  const chart=createChart(target,{
    width:target.clientWidth,height:390,
    layout:{background:{type:ColorType.Solid,color:light?'#ffffff':'#10131f'},textColor:light?'#727b94':'#838aa6',fontSize:11},
    grid:{vertLines:{color:light?'#e9edf5':'#1c2030'},horzLines:{color:light?'#e9edf5':'#1c2030'}},
    rightPriceScale:{borderColor:light?'#e2e6ef':'#272c3f'},timeScale:{borderColor:light?'#e2e6ef':'#272c3f',timeVisible:true,secondsVisible:false},
    crosshair:{vertLine:{color:'#7777bd'},horzLine:{color:'#7777bd'}}
  })
  const candle=chart.addSeries(CandlestickSeries,{upColor:'#29d59b',downColor:'#f36d88',borderVisible:false,wickUpColor:'#29d59b',wickDownColor:'#f36d88'})
  candle.setData(candles.map(x=>({time:Math.floor(x.time/1000) as any,open:x.open,high:x.high,low:x.low,close:x.close})))
  if(volume){const bars=chart.addSeries(HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'volume',lastValueVisible:false,priceLineVisible:false});bars.setData(candles.map(x=>({time:Math.floor(x.time/1000) as any,value:x.volume,color:x.close>=x.open?'#29d59b29':'#f36d8829'})));chart.priceScale('volume').applyOptions({scaleMargins:{top:0.83,bottom:0}})}
  if(indicators){for(const [n,color] of [[20,'#8868ff'],[50,'#e4b86a'],[200,'#459fee']] as const){const series=chart.addSeries(LineSeries,{color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,title:'EMA'+n});series.setData(ema(candles,n))}}
  const lines:IPriceLine[]=[]
  const price=(p:number,color:string,title:string)=>lines.push(candle.createPriceLine({price:p,color,lineWidth:2,lineStyle:2,axisLabelVisible:true,title}))
  if(signal&&signal.side!=='WAIT'&&signal.entry&&signal.stopLoss){price(signal.entry,'#a2abce','ENTRY');price(signal.stopLoss,'#f36d88','STOP');signal.takeProfits.forEach((p,i)=>price(p,'#29d59b','TP'+(i+1)))}
  chart.timeScale().fitContent()
  const ro=new ResizeObserver(()=>chart.applyOptions({width:target.clientWidth}))
  ro.observe(target)
  return()=>{ro.disconnect();lines.forEach(l=>candle.removePriceLine(l));chart.remove()}
 },[candles,signal,indicators,volume,light])
 return <div className="chart-wrap"><div className="chart-bar"><span className="chart-label"><BarChart3 size={15}/> Свечной график · BingX</span><div className="chart-switches"><button className={indicators?'chip on':'chip'} onClick={()=>setIndicators(!indicators)} title="EMA 20/50/200"><Layers3 size={13}/> EMA</button><button className={volume?'chip on':'chip'} onClick={()=>setVolume(!volume)} title="Объём">VOL</button></div></div><div ref={host} className="chart-host"/></div>
}

export function Sparkline({values,positive}:{values:number[],positive:boolean}){
 if(values.length<3)return <span className="spark-empty">—</span>
 const min=Math.min(...values),max=Math.max(...values),d=max-min||1
 const path=values.map((n,i)=>`${i?'L':'M'} ${(i/(values.length-1)*118).toFixed(1)} ${(35-((n-min)/d*31)).toFixed(1)}`).join(' ')
 return <svg aria-hidden="true" className="sparkline" viewBox="0 0 120 40"><path d={path} stroke={positive?'#2dd6a0':'#f26b8a'} fill="none" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
}
