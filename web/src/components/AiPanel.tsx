import {useEffect,useRef,useState} from 'react';
import {Bot,FileText,Layers,LoaderCircle,MapPin,Orbit,Search,Send,ShieldCheck,Sparkles,TriangleAlert,X} from 'lucide-react';
import './ai-panel.css';

/* AI yordamchi — Abubakr'ning Explorer sahifasi ichidagi panel.
   Savol → AI TerraMind vositalarini chaqiradi: 1) Oy/Mars joyini xaritada belgilaydi,
   2) Analog Finder Yerni skanerlaydi, 3) natija 3D da solishtiriladi. Barcha ballar algoritmdan. */

type Summary={p5:number|null;median:number|null;p95:number|null;count:number};
type MapMeta={kind:'polar'|'equirect';image:string;marker:{x:number;y:number};box:{x0:number;y0:number;x1:number;y1:number};caption:string};
export type AiReference={id:string;name:string;body:'mars'|'moon';center:{lat:number;lon:number};dataset?:string;window_km:number;grid_m:number;metric_summary?:Record<'slope_deg'|'relief_m'|'tri_m',Summary>;map?:MapMeta|null;map_error?:string;landing?:Landing|null};
export type Landing={flat_lt5:number|null;lt15:number|null;hazard_gt15:number|null};
export type AiLead={lat:number;lon:number;rank?:number;overall_A:number;slope_deg?:number;relief_m?:number;tri_m?:number;satellite?:string};
export type AiSearch={reference:{id:string;name:string};region:{id:string;name:string;bbox:[number,number,number,number]};counts:{windows:number;scored:number;water:number};score_distribution:{max:number;median:number}|null;top:AiLead[];known_sites:{site:string;name:string;rank:number;of:number;top_percent:number;score:number}[]};
type Message={role:'user'|'assistant';content:string;unverified?:string[];error?:boolean};
type Overview={references:AiReference[];pending_references?:{id:string;name:string;state:string}[];regions:{id:string;name:string}[];searches:{id:string}[];ai_available:boolean};

const EXAMPLES=[
  'Menga Oydagi LOLA ning yerdagi relyefiga mos bo‘lgan joyni topib ber',
  'G‘arbiy O‘zbekistonda Meridiani Planum (Opportunity) ga o‘xshash joylar qayerda?',
  'Yuta (MDRS) atrofida Gale kraterining analoglarini top',
];
const pc=(v:number|null|undefined)=>v===null||v===undefined?'—':`${(v*100).toFixed(0)} %`;
function LandingBar({l,compact}:{l:Landing|null|undefined;compact?:boolean}){if(!l||l.flat_lt5===null)return null;const f=(l.flat_lt5??0)*100,c=((l.lt15??0)-(l.flat_lt5??0))*100,h=(l.hazard_gt15??0)*100;return <div className={`ai-landing ${compact?'compact':''}`} title="Qiyalik < 5° — tekis, 5–15° — ehtiyot, ≥ 15° — xavfli. O‘lchangan balandlikdan oddiy qo‘nish skriningi, missiya bahosi emas."><span>Qo‘nish uchun tekis maydon</span><i><b className="flat" style={{width:`${f}%`}}/><b className="caution" style={{width:`${c}%`}}/><b className="hazard" style={{width:`${h}%`}}/></i><em><strong>{pc(l.flat_lt5)}</strong> &lt;5° · {pc(l.lt15)} &lt;15° · {pc(l.hazard_gt15)} xavfli</em></div>}
const nf=(v:number|null|undefined,d=2)=>v===null||v===undefined||!Number.isFinite(v)?'—':v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const coord=(p:{lat:number;lon:number})=>`${Math.abs(p.lat).toFixed(3)}° ${p.lat<0?'J':'Sh'} · ${Math.abs(p.lon).toFixed(3)}° ${p.lon<0?'G‘':'Sh'}`;
async function api<T>(url:string,init?:RequestInit):Promise<T>{const r=await fetch(url,init);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof j.detail==='string'?j.detail:`Server javobi: ${r.status}`);return j as T}

const ZOOM=6;
function ReferenceMap({meta}:{meta:MapMeta}){
  const {marker:m,box:b}=meta,z=meta.kind==='equirect'?ZOOM:1;
  const clamp=(v:number)=>z===1?.5:Math.min(Math.max(v,1/(2*z)),1-1/(2*z));
  const cx=clamp(m.x),cy=clamp(m.y),fx=(x:number)=>z===1?x:.5+(x-cx)*z,fy=(y:number)=>z===1?y:.5+(y-cy)*z;
  const img=z===1?undefined:{position:'absolute' as const,width:`${z*100}%`,height:`${z*100}%`,maxWidth:'none',left:`${(.5-cx*z)*100}%`,top:`${(.5-cy*z)*100}%`};
  return <div className={`ai-refmap ${meta.kind}`}><img src={meta.image} alt={meta.caption} style={img}/>
    <span className="ai-refbox" style={{left:`${fx(b.x0)*100}%`,top:`${fy(b.y0)*100}%`,width:`${Math.max((fx(b.x1)-fx(b.x0))*100,1.5)}%`,height:`${Math.max((fy(b.y1)-fy(b.y0))*100,1.5)}%`}}/>
    <span className="ai-refpin" style={{left:`${fx(m.x)*100}%`,top:`${fy(m.y)*100}%`}}/></div>;
}

export type AiPanelProps={
  open:boolean;onClose:()=>void;
  reference:AiReference|null;search:AiSearch|null;selected:number;
  onReference:(r:AiReference)=>void;onSearch:(s:AiSearch|null)=>void;onSelect:(i:number)=>void;
  onCompare:(lead:AiLead)=>void;
};

export default function AiPanel({open,onClose,reference,search,selected,onReference,onSearch,onSelect,onCompare}:AiPanelProps){
  const [ov,setOv]=useState<Overview|null>(null),[messages,setMessages]=useState<Message[]>([]),[input,setInput]=useState(''),[busy,setBusy]=useState(false);
  const [manualRef,setManualRef]=useState(''),[manualRegion,setManualRegion]=useState('');
  const [leadLanding,setLeadLanding]=useState<Record<string,Landing>>({});
  const lead=search?.top[selected];
  useEffect(()=>{if(!search||!lead)return;const k=`${search.region.id}|${lead.lat},${lead.lon}`;if(leadLanding[k])return;api<Landing>(`/api/tm/landing/point?region=${search.region.id}&lat=${lead.lat}&lon=${lead.lon}`).then(l=>setLeadLanding(m=>({...m,[k]:l}))).catch(()=>{})},[search,lead]);
  const thread=useRef<HTMLDivElement>(null);
  useEffect(()=>{api<Overview>('/api/tm/overview').then(o=>{setOv(o);setManualRef(o.references[0]?.id??'');setManualRegion(o.regions.find(r=>r.id==='uzbekistan_west')?.id??o.regions[0]?.id??'')}).catch(()=>setOv({references:[],regions:[],searches:[],ai_available:false}))},[]);
  useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight,behavior:'smooth'})},[messages,busy,reference,search]);

  const showReference=async(id:string)=>{const r=await api<AiReference>(`/api/tm/reference/${id}`);onReference(r);if(search&&search.reference.id!==id)onSearch(null);setManualRef(id);return r};
  const showSearch=async(id:string)=>{const v=await api<AiSearch>(`/api/tm/search/${id}`);onSearch(v);onSelect(0);setManualRegion(v.region.id);return v};
  const ask=async(q:string)=>{q=q.trim();if(!q||busy)return;setInput('');const history=messages.map(m=>({role:m.role,content:m.content}));setMessages(m=>[...m,{role:'user',content:q}]);setBusy(true);
    try{const r=await api<{answer:string;unverified_numbers:string[];steps:{kind:string;reference?:{id:string};search_id?:string}[]}>('/api/tm/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});
      for(const st of r.steps){if(st.kind==='reference'&&st.reference)await showReference(st.reference.id);else if(st.kind==='search'&&st.search_id)await showSearch(st.search_id)}
      setMessages(m=>[...m,{role:'assistant',content:r.answer,unverified:r.unverified_numbers}]);
    }catch(e){setMessages(m=>[...m,{role:'assistant',content:(e as Error).message,error:true}])}finally{setBusy(false)}};
  const manual=async()=>{if(!manualRef||busy)return;setBusy(true);try{await showReference(manualRef);const id=`${manualRef}__${manualRegion}`;if(ov?.searches.some(s=>s.id===id))await showSearch(id);else{onSearch(null);setMessages(m=>[...m,{role:'assistant',content:`Bu juftlik uchun qidiruv hali bajarilmagan. Serverda: python -m terramind search --reference ${manualRef} --region ${manualRegion}`,error:true}])}}catch(e){setMessages(m=>[...m,{role:'assistant',content:(e as Error).message,error:true}])}finally{setBusy(false)}};
  const ms=reference?.metric_summary;

  return <aside className={`ai-panel ${open?'open':''}`} aria-label="AI yordamchi" aria-hidden={!open}>
    <div className="ai-head"><div><span className="science-kicker">AI YORDAMCHI</span><h3>Oy yoki Marsdagi joyning Yerdagi egizagini toping</h3></div><button onClick={onClose} aria-label="Panelni yopish"><X size={18}/></button></div>
    <div className="ai-thread" ref={thread}>
      {!messages.length&&<div className="ai-examples">{EXAMPLES.map(q=><button key={q} onClick={()=>ask(q)} disabled={busy||!ov?.ai_available}><Sparkles size={13}/>{q}</button>)}</div>}
      {ov&&!ov.ai_available&&<p className="ai-note"><TriangleAlert size={13}/>.env faylida OPENROUTER_API_KEY yo‘q — chat ishlamaydi, pastdagi «to‘g‘ridan-to‘g‘ri» rejim ishlaydi.</p>}
      {ov?.pending_references?.map(p=><p key={p.id} className="ai-note"><TriangleAlert size={13}/>{p.name}: oyna hali tasdiqlanmagan. Buyruq: <code>python -m terramind approve --site {p.id}</code></p>)}
      {messages.map((m,i)=><div key={i} className={`ai-bubble ${m.role} ${m.error?'error':''}`}>{m.role==='assistant'&&<span className="ai-who"><Bot size={12}/>TerraMind</span>}<p>{m.content}</p>
        {m.role==='assistant'&&!m.error&&(m.unverified?.length?<span className="ai-verify warn"><TriangleAlert size={12}/>Natijalarda yo‘q raqamlar: {m.unverified.join(', ')}</span>:<span className="ai-verify ok"><ShieldCheck size={12}/>Har bir raqam hisoblangan natijalarga mos</span>)}</div>)}
      {busy&&<div className="ai-bubble assistant thinking"><LoaderCircle size={14} className="rotating"/>Joy belgilanmoqda, Yer skanerlanmoqda…</div>}

      {reference&&<section className="ai-card"><header><span className={`ai-tag ${reference.body}`}>{reference.body==='moon'?'OY':'MARS'}</span><div><strong>{reference.name}</strong><small>{coord(reference.center)} · {reference.dataset??''}</small></div></header>
        {reference.map?<ReferenceMap meta={reference.map}/>:<p className="ai-note">{reference.map_error??'Xarita mavjud emas'}</p>}
        <div className="ai-refrow"><img src={`/api/tm/window-image/${reference.id}.png`} alt="Tanlangan oynaning relyefi" onError={e=>{e.currentTarget.style.display='none'}}/>
          <dl><div><dt>Median qiyalik</dt><dd>{nf(ms?.slope_deg?.median,1)}°</dd></div><div><dt>Median notekislik (TRI)</dt><dd>{nf(ms?.tri_m?.median,1)} m</dd></div><div><dt>Relyef, 5–95%</dt><dd>{nf(ms?.relief_m?.p5,0)} … {nf(ms?.relief_m?.p95,0)} m</dd></div></dl></div>
        <LandingBar l={reference.landing}/>
        <small className="ai-fine">Oq kvadrat — {reference.window_km} km oyna. U ball hisoblanishidan oldin inson tomonidan tasdiqlangan.</small></section>}

      {search&&<section className="ai-card"><header><span className="ai-tag earth">YER</span><div><strong>{search.region.name}</strong><small>{search.counts.scored.toLocaleString('en-US')} oyna baholandi · suv {search.counts.water} · eng yaxshisi {nf(search.score_distribution?.max)}</small></div></header>
        <ol className="ai-leads">{search.top.slice(0,8).map((l,i)=><li key={`${l.lat},${l.lon}`} className={i===selected?'selected':''}>
          <button className="ai-lead" onClick={()=>onSelect(i)}><span className="ai-rank">{i+1}</span><span className="ai-coord">{coord(l)}</span><strong>{nf(l.overall_A)}</strong></button>
          {i===selected&&<div className="ai-leaddetail"><div className="ai-bars">{(['slope_deg','relief_m','tri_m'] as const).map(k=><label key={k}><span>{k==='slope_deg'?'Qiyalik':k==='relief_m'?'Relyef':'Notekislik'}</span><i><b style={{width:`${(l[k]??0)*100}%`}}/></i><em>{nf(l[k])}</em></label>)}</div>
            <LandingBar l={leadLanding[`${search.region.id}|${l.lat},${l.lon}`]} compact/>
            <div className="ai-actions"><button className="primary" onClick={()=>onCompare(l)}><Layers size={13}/>3D da solishtirish</button><a href={l.satellite} target="_blank" rel="noreferrer"><MapPin size={13}/>Sun’iy yo‘ldosh</a><a href={`/api/tm/report/${search.reference.id}__${search.region.id}?lat=${l.lat}&lon=${l.lon}`} target="_blank" rel="noreferrer" title="Bir sahifali missiya hisoboti: ikkala oyna, raqamlar, manbalar, tekshiruv holati. Brauzerdan PDF qilib saqlash mumkin."><FileText size={13}/>Hisobot</a></div></div>}
        </li>)}</ol>
        {search.known_sites.map(k=><p key={k.site} className="ai-known">Ma’lum analog — {k.name}: {k.of} oynadan {k.rank}-o‘rin (top {k.top_percent}%), ball {nf(k.score)}.</p>)}
        <small className="ai-fine">Joylar Yer xaritasida ham belgilandi. Bu — nomzodlar; analog deb atash uchun inson sun’iy yo‘ldosh suratida tekshiradi.</small></section>}
    </div>
    <form className="ai-input" onSubmit={e=>{e.preventDefault();ask(input)}}>
      <textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(input)}}} rows={2} maxLength={600} placeholder="Istalgan tilda yozing…" disabled={busy}/>
      <button type="submit" disabled={busy||!input.trim()} aria-label="Yuborish"><Send size={15}/></button>
    </form>
    {ov&&<div className="ai-manual"><span>Yoki to‘g‘ridan-to‘g‘ri tanlang</span>
      <select value={manualRef} onChange={e=>setManualRef(e.target.value)} aria-label="Mos keltiriladigan joy">{ov.references.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
      <select value={manualRegion} onChange={e=>setManualRegion(e.target.value)} aria-label="Yerdagi hudud">{ov.regions.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
      <button onClick={manual} disabled={busy}><Search size={13}/>Ko‘rsatish</button></div>}
    <div className="ai-foot"><Orbit size={12}/>AI faqat vositani tanlaydi va tushuntiradi; har bir ballni algoritm hisoblaydi.</div>
  </aside>;
}
