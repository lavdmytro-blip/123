export type Timeframe = '1m'|'5m'|'15m'|'30m'|'1h'|'4h'|'1d'
export type Side = 'LONG'|'SHORT'|'WAIT'
export interface Ticker {symbol:string;lastPrice:number;change24h:number;volume24h:number;high24h:number;low24h:number;time:number}
export interface Candle {time:number;open:number;high:number;low:number;close:number;volume:number;closeTime:number}
export interface Reason {direction:Side;text:string;weight:number}
export interface Signal {symbol:string;interval:Timeframe;generatedAt:number;side:Side;price:number|null;entry:number|null;stopLoss:number|null;takeProfits:number[];riskReward:number|null;strength:number;reasons:Reason[];risks:string[];metrics:Record<string,number|null>;summary:string;aiSummary?:string|null;levels:Record<string,number>;method:string}
export interface SavedSignal {id:number;symbol:string;interval:Timeframe;side:Side;entry:number|null;stopLoss:number|null;takeProfits:number[];status:string;createdAt:string;result:Signal}
export interface Alert {id:number;symbol:string;targetPrice:number;active:boolean}
export interface Watch {symbol:string;interval:Timeframe;lastSide:Side}
export interface Settings {userId:number;language:'ru'|'en';theme:'dark'|'light';interval:Timeframe;notifications:boolean;chatConnected:boolean}
export type Tab = 'home'|'terminal'|'auto'|'history'|'alerts'|'settings'
export interface AutoSignal {id:number;symbol:string;interval:Timeframe;side:Side;entry:number;stopLoss:number;takeProfits:number[];status:string;tpReached:number;createdAt:string;result:Signal}
export interface ScannerProgress {total:number;scanned:number;round:number;lastSymbol:string;lastUpdate:string|null;lastCompleted:string|null;error:string}
export interface AutoFeedResponse {scanner:ScannerProgress;topSymbols:string[];signals:AutoSignal[];prices:Record<string,number>;pricesFresh:boolean;updatedAt:number;subscribed:boolean;scannerEnabled:boolean}
