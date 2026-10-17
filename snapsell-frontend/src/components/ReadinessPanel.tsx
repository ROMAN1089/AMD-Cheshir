'use client';
import {ArrowUpRight,Camera,CheckCircle2,DollarSign,PackageCheck,ShieldCheck} from 'lucide-react';
type Data=Record<string,any>;
export function ReadinessPanel({items,onReview,onChannels}:{items:Data[];onReview:(item:Data)=>void;onChannels:(id:string)=>void}){
 const active=items.filter(item=>!item.archived_at&&!['sold','sale_pending'].includes(item.status));
 const hasPhoto=(item:Data)=>item.image?.startsWith('/media/');
 const priced=(item:Data)=>Number(item.price)>0&&Number(item.price)>=Math.max(Number(item.reserve||0),Number(item.cost||0)/(1-Number(item.fee_rate||0)));
 const ready=(item:Data)=>hasPhoto(item)&&item.confirmed&&priced(item);
 const queue=active.filter(item=>item.status==='draft').sort((left,right)=>Number(ready(left))-Number(ready(right))).slice(0,4);
 if(!active.length)return null;
 return <section className="panel readiness-panel"><div className="section-head"><div><div className="eyebrow">FROM CAPTURE TO CONFIDENT LISTING</div><h2>Your next useful move.</h2><p className="muted">Finish the checks that turn a draft into a marketplace listing.</p></div><span className="badge green">{active.filter(ready).length} ready to prepare</span></div><div className="readiness-stages">{[{name:'With photos',count:active.filter(hasPhoto).length,icon:Camera},{name:'Facts reviewed',count:active.filter(item=>item.confirmed).length,icon:ShieldCheck},{name:'Price set',count:active.filter(priced).length,icon:DollarSign},{name:'Ready for a kit',count:active.filter(ready).length,icon:PackageCheck}].map(({name,count,icon:Icon})=><div key={name}><Icon size={18}/><strong>{count}<small> / {active.length}</small></strong><span>{name}</span></div>)}</div>{queue.map(item=>{const next=!hasPhoto(item)?'Add product photos':!item.confirmed?'Review product facts':!priced(item)?'Set a supported asking price':'Prepare marketplace listing';return <button className="readiness-row" key={item.id} onClick={()=>ready(item)?onChannels(item.id):onReview(item)}><img src={item.image} alt=""/><span><strong>{item.title}</strong><small>{next}</small></span>{ready(item)?<CheckCircle2 size={17}/>:<ArrowUpRight size={17}/>}</button>;})}<p className="footnote">Ready means the saved photo, seller-confirmed facts and asking price pass the local checks. Each marketplace can require additional fields.</p></section>;
}
