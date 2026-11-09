import {createContext,useContext,useEffect,useState,type ReactNode} from 'react'
import {Coins} from 'lucide-react'
import {getCoinLogos} from './api'

const LogosContext=createContext<Record<string,string>>({})
// The community icon library is a backstop if CoinGecko images cannot be loaded.
// Unknown coins use a coin graphic, NEVER a misleading logo or the first letter.
const fallbackSymbols=new Set(('BTC ETH SOL XRP BNB DOGE ADA AVAX DOT TON LINK TRX LTC BCH ETC XLM ATOM ALGO AAVE UNI SUSHI CRV COMP MKR YFI FTM MATIC POL NEAR OP ARB INJ FIL ICP EGLD HBAR VET ZEC DASH EOS XMR ZRX BAT SAND MANA GALA CHZ RUNE KAVA KSM LDO QNT GRT ENJ APE FLOW NEO IOTA RSR 1INCH BTT SNX WAVES ZIL CAKE STX CELO XTZ THETA SXP LRC QTUM KNC ANKR OCEAN ONT ZEN HOT RVN NMR WOO GMT MASK DYDX AXS FET CFX COTI FXS BAND DENT IOST YGG ILV JST RLC SKL API3 AUDIO SFP ROSE BAL LPT REEF ZRX WAXP AR RPL BLUR JASMY TONC BNB BEAM SUI').split(' '))
const CDN='https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/'

export function CoinLogoProvider({children}:{children:ReactNode}){
  const [logos,setLogos]=useState<Record<string,string>>({})
  useEffect(()=>{let valid=true;void getCoinLogos().then(x=>{if(valid)setLogos(x.images)}).catch(()=>{});return()=>{valid=false}},[])
  return <LogosContext.Provider value={logos}>{children}</LogosContext.Provider>
}

export function CoinLogo({symbol,small=false}:{symbol:string;small?:boolean}){
  const logos=useContext(LogosContext)
  const base=symbol.split('-')[0].toUpperCase()
  const normalized=/^\d{3,6}[A-Z]+$/.test(base)?base.replace(/^\d{3,6}/,''):base
  const branded=logos[base]||logos[normalized]
  const fallback=fallbackSymbols.has(normalized)?`${CDN}${normalized.toLowerCase()}.png`:null
  const [failed,setFailed]=useState(0)
  useEffect(()=>setFailed(0),[branded,fallback,base])
  const src=failed===0?(branded||fallback):failed===1&&branded?fallback:null
  return <div className={'coin-logo real-coin-logo'+(small?' small':'')} title={base+' logo'}>
    {src?<img src={src} loading="lazy" alt={base+' logo'} onError={()=>setFailed(x=>x+1)} referrerPolicy="no-referrer"/>:<Coins size={small?18:21} aria-label={'Значок '+base}/>}
  </div>
}
