import {useEffect,useRef,useState} from 'react';
import {Bot,FileText,Layers,LoaderCircle,MapPin,Orbit,Search,Send,ShieldCheck,Sparkles,TriangleAlert,X} from 'lucide-react';
import {useI18n} from '../i18n';
import './ai-panel.css';

/* AI yordamchi — Abubakr'ning Explorer sahifasi ichidagi panel.
   Savol → AI TerraMind vositalarini chaqiradi: 1) Oy/Mars joyini xaritada belgilaydi,
   2) Analog Finder Yerni skanerlaydi, 3) natija 3D da solishtiriladi. Barcha ballar algoritmdan. */

type Summary={p5:number|null;median:number|null;p95:number|null;count:number};
type MapMeta={kind:'polar'|'equirect';image:string;marker:{x:number;y:number};box:{x0:number;y0:number;x1:number;y1:number};caption:string};
export type AiReference={id:string;name:string;body:'mars'|'moon';center:{lat:number;lon:number};dataset?:string;window_km:number;grid_m:number;metric_summary?:Record<'slope_deg'|'relief_m'|'tri_m',Summary>;map?:MapMeta|null;map_error?:string;landing?:Landing|null;terrain_url?:string};
export type Landing={flat_lt5:number|null;lt15:number|null;hazard_gt15:number|null};
export type AiLead={lat:number;lon:number;rank?:number;overall_A:number;slope_deg?:number;relief_m?:number;tri_m?:number;satellite?:string};
export type AiSearch={reference:{id:string;name:string};region:{id:string;name:string;bbox:[number,number,number,number]};counts:{windows:number;scored:number;water:number};score_distribution:{max:number;median:number}|null;top:AiLead[];known_sites:{site:string;name:string;rank:number;of:number;top_percent:number;score:number}[]};
type Message={role:'user'|'assistant';content:string;unverified?:string[];error?:boolean};
type Overview={references:AiReference[];pending_references?:{id:string;name:string;state:string}[];regions:{id:string;name:string}[];searches:{id:string}[];ai_available:boolean};

const EXAMPLES=[
  {ru:'Найди на Земле рельеф, похожий на выбранный участок Луны по данным LOLA.',en:'Find Earth terrain similar to the selected lunar area using LOLA data.',uz:'LOLA ma’lumotlari bo‘yicha tanlangan Oy hududiga o‘xshash Yer relyefini top.'},
  {ru:'Где на западе Узбекистана есть места, похожие на Meridiani Planum (Opportunity)?',en:'Where in western Uzbekistan is the terrain similar to Meridiani Planum (Opportunity)?',uz:'G‘arbiy O‘zbekistonda Meridiani Planum (Opportunity) ga o‘xshash joylar qayerda?'},
  {ru:'Найди аналоги кратера Гейл в окрестностях MDRS в Юте.',en:'Find analogues of Gale crater near MDRS in Utah.',uz:'Yuta (MDRS) atrofida Gale kraterining analoglarini top.'},
];
const pc=(v:number|null|undefined)=>v===null||v===undefined?'—':`${(v*100).toFixed(0)} %`;
function LandingBar({l,compact}:{l:Landing|null|undefined;compact?:boolean}){const {t}=useI18n();if(!l||l.flat_lt5===null)return null;const f=(l.flat_lt5??0)*100,c=((l.lt15??0)-(l.flat_lt5??0))*100,h=(l.hazard_gt15??0)*100;return <div className={`ai-landing ${compact?'compact':''}`} title={t({ru:'Уклон <5° — пологий, 5–15° — осторожность, ≥15° — крутой. Предварительный анализ высот, а не оценка безопасности посадки.',en:'Slope <5°: gentle; 5–15°: caution; ≥15°: steep. Preliminary elevation screening, not a landing safety assessment.',uz:'Qiyalik <5° — tekis, 5–15° — ehtiyot, ≥15° — tik. Balandlik ma’lumotlari bo‘yicha dastlabki tahlil, qo‘nish xavfsizligi bahosi emas.'})}><span>{t({ru:'Доля пологого рельефа',en:'Gentle terrain share',uz:'Tekis relyef ulushi'})}</span><i><b className="flat" style={{width:`${f}%`}}/><b className="caution" style={{width:`${c}%`}}/><b className="hazard" style={{width:`${h}%`}}/></i><em><strong>{pc(l.flat_lt5)}</strong> &lt;5° · {pc(l.lt15)} &lt;15° · {pc(l.hazard_gt15)} {t({ru:'крутой',en:'steep',uz:'tik'})}</em></div>}
const coord=(p:{lat:number;lon:number})=>`${Math.abs(p.lat).toFixed(3)}° ${p.lat<0?'S':'N'} · ${Math.abs(p.lon).toFixed(3)}° ${p.lon<0?'W':'E'}`;
class ApiError extends Error{constructor(readonly status:number,readonly detail?:string){super(detail??String(status));}}
async function api<T>(url:string,init?:RequestInit):Promise<T>{const r=await fetch(url,init);const j=await r.json().catch(()=>({}));if(!r.ok)throw new ApiError(r.status,typeof j.detail==='string'?j.detail:undefined);return j as T}

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
  const {t,locale}=useI18n();
  const nf=(v:number|null|undefined,d=2)=>v===null||v===undefined||!Number.isFinite(v)?'—':v.toLocaleString(locale,{maximumFractionDigits:d,minimumFractionDigits:d});
  const errorText=(error:unknown)=>error instanceof ApiError?(error.detail??t({ru:`Сервис вернул ошибку (${error.status}). Попробуйте ещё раз.`,en:`The service returned an error (${error.status}). Please try again.`,uz:`Xizmat xato qaytardi (${error.status}). Qayta urinib ko‘ring.`})):t({ru:'Не удалось связаться с сервисом. Проверьте подключение и попробуйте ещё раз.',en:'Could not reach the service. Check your connection and try again.',uz:'Xizmatga ulanib bo‘lmadi. Ulanishni tekshirib, qayta urinib ko‘ring.'});
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
    }catch(e){setMessages(m=>[...m,{role:'assistant',content:errorText(e),error:true}])}finally{setBusy(false)}};
  const manual=async()=>{if(!manualRef||!manualRegion||busy)return;setBusy(true);try{await showReference(manualRef);const id=`${manualRef}__${manualRegion}`;if(ov?.searches.some(s=>s.id===id))await showSearch(id);else{onSearch(null);setMessages(m=>[...m,{role:'assistant',content:t({ru:'Для этой пары ещё нет подготовленных результатов. Выберите другой эталон или регион.',en:'Results for this pair are not ready yet. Choose another reference or region.',uz:'Bu juftlik uchun natijalar hali tayyor emas. Boshqa namuna yoki hududni tanlang.'}),error:true}])}}catch(e){setMessages(m=>[...m,{role:'assistant',content:errorText(e),error:true}])}finally{setBusy(false)}};
  const ms=reference?.metric_summary;

  return <aside className={`ai-panel ${open?'open':''}`} aria-label={t({ru:'ИИ-помощник',en:'AI assistant',uz:'AI yordamchi'})} aria-hidden={!open}>
    <div className="ai-head"><div><span className="science-kicker">{t({ru:'ИИ-ПОМОЩНИК',en:'AI ASSISTANT',uz:'AI YORDAMCHI'})}</span><h3>{t({ru:'Найдите земной аналог лунного или марсианского рельефа',en:'Find an Earth analogue of lunar or Martian terrain',uz:'Oy yoki Mars relyefining Yerdagi o‘xshashini toping'})}</h3></div><button onClick={onClose} aria-label={t({ru:'Закрыть панель',en:'Close panel',uz:'Panelni yopish'})}><X size={18}/></button></div>
    <div className="ai-thread" ref={thread}>
      {!messages.length&&<div className="ai-examples">{EXAMPLES.map((example,i)=>{const q=t(example);return <button key={i} onClick={()=>ask(q)} disabled={busy||!ov?.ai_available}><Sparkles size={13}/>{q}</button>})}</div>}
      {ov&&!ov.ai_available&&<p className="ai-note"><TriangleAlert size={13}/>{t({ru:'Чат с ИИ сейчас недоступен. Подготовленные результаты можно открыть через выбор эталона и региона ниже.',en:'AI chat is currently unavailable. You can open prepared results by selecting a reference and region below.',uz:'AI chat hozircha mavjud emas. Quyida namuna va hududni tanlab, tayyor natijalarni ochishingiz mumkin.'})}</p>}
      {ov?.pending_references?.map(p=><p key={p.id} className="ai-note"><TriangleAlert size={13}/>{p.name}: {t({ru:'эталонный участок ещё проходит проверку и пока недоступен для сравнения.',en:'the reference area is still awaiting review and is not yet available for comparison.',uz:'namuna hudud hali tekshiruvdan o‘tmagan va taqqoslash uchun tayyor emas.'})}</p>)}
      {messages.map((m,i)=><div key={i} className={`ai-bubble ${m.role} ${m.error?'error':''}`}>{m.role==='assistant'&&<span className="ai-who"><Bot size={12}/>TerraMind</span>}<p>{m.content}</p>
        {m.role==='assistant'&&!m.error&&(m.unverified?.length?<span className="ai-verify warn"><TriangleAlert size={12}/>{t({ru:'Числа, не подтверждённые результатами:',en:'Numbers not verified against the results:',uz:'Natijalar bilan tasdiqlanmagan raqamlar:'})} {m.unverified.join(', ')}</span>:<span className="ai-verify ok"><ShieldCheck size={12}/>{t({ru:'Числа сверены с рассчитанными результатами',en:'Numbers checked against computed results',uz:'Raqamlar hisoblangan natijalar bilan tekshirildi'})}</span>)}</div>)}
      {busy&&<div className="ai-bubble assistant thinking"><LoaderCircle size={14} className="rotating"/>{t({ru:'Подготовка участка и поиск земных аналогов…',en:'Preparing the area and searching for Earth analogues…',uz:'Hudud tayyorlanmoqda va Yerdagi o‘xshashlar izlanmoqda…'})}</div>}

      {reference&&<section className="ai-card"><header><span className={`ai-tag ${reference.body}`}>{reference.body==='moon'?t({ru:'ЛУНА',en:'MOON',uz:'OY'}):t({ru:'МАРС',en:'MARS',uz:'MARS'})}</span><div><strong>{reference.name}</strong><small>{coord(reference.center)} · {reference.dataset??''}</small></div></header>
        {reference.map?<ReferenceMap meta={reference.map}/>:reference.id.includes('@')?<p className="ai-note">{t({ru:'Исследовательская точка — не проверенный участок. Метод расчёта тот же.',en:'Exploration point — not a reviewed site. Same method.',uz:'Tadqiqot nuqtasi — tekshiruvdan o‘tgan joy emas. Hisob usuli bir xil.'})}</p>:<p className="ai-note">{reference.map_error??t({ru:'Карта недоступна',en:'Map unavailable',uz:'Xarita mavjud emas'})}</p>}
        <div className="ai-refrow"><img src={`/api/tm/window-image/${reference.id}.png`} alt={t({ru:'Рельеф выбранного участка',en:'Terrain of the selected area',uz:'Tanlangan hudud relyefi'})} onError={e=>{e.currentTarget.style.display='none'}}/>
          <dl><div><dt>{t({ru:'Медианный уклон',en:'Median slope',uz:'Median qiyalik'})}</dt><dd>{nf(ms?.slope_deg?.median,1)}°</dd></div><div><dt>{t({ru:'Медианная неровность (TRI)',en:'Median ruggedness (TRI)',uz:'Median notekislik (TRI)'})}</dt><dd>{nf(ms?.tri_m?.median,1)} m</dd></div><div><dt>{t({ru:'Рельеф, 5–95%',en:'Relief, 5–95%',uz:'Relyef, 5–95%'})}</dt><dd>{nf(ms?.relief_m?.p5,0)} … {nf(ms?.relief_m?.p95,0)} m</dd></div></dl></div>
        <LandingBar l={reference.landing}/>
        <small className="ai-fine">{t({ru:`Белый квадрат — участок размером ${reference.window_km} км, проверенный человеком до расчёта оценки.`,en:`The white square is a ${reference.window_km} km area reviewed by a person before scoring.`,uz:`Oq kvadrat — ${reference.window_km} km hudud. U ball hisoblanishidan oldin inson tomonidan tasdiqlangan.`})}</small></section>}

      {search&&<section className="ai-card"><header><span className="ai-tag earth">{t({ru:'ЗЕМЛЯ',en:'EARTH',uz:'YER'})}</span><div><strong>{search.region.name}</strong><small>{t({ru:`Оценено участков: ${search.counts.scored.toLocaleString(locale)} · вода: ${search.counts.water.toLocaleString(locale)} · лучшая оценка: ${nf(search.score_distribution?.max)}`,en:`${search.counts.scored.toLocaleString(locale)} areas scored · water: ${search.counts.water.toLocaleString(locale)} · best: ${nf(search.score_distribution?.max)}`,uz:`${search.counts.scored.toLocaleString(locale)} hudud baholandi · suv: ${search.counts.water.toLocaleString(locale)} · eng yaxshisi: ${nf(search.score_distribution?.max)}`})}</small></div></header>
        <ol className="ai-leads">{search.top.slice(0,8).map((l,i)=><li key={`${l.lat},${l.lon}`} className={i===selected?'selected':''}>
          <button className="ai-lead" onClick={()=>onSelect(i)}><span className="ai-rank">{i+1}</span><span className="ai-coord">{coord(l)}</span><strong>{nf(l.overall_A)}</strong></button>
          {i===selected&&<div className="ai-leaddetail"><div className="ai-bars">{(['slope_deg','relief_m','tri_m'] as const).map(k=><label key={k}><span>{k==='slope_deg'?t({ru:'Уклон',en:'Slope',uz:'Qiyalik'}):k==='relief_m'?t({ru:'Рельеф',en:'Relief',uz:'Relyef'}):t({ru:'Неровность',en:'Ruggedness',uz:'Notekislik'})}</span><i><b style={{width:`${(l[k]??0)*100}%`}}/></i><em>{nf(l[k])}</em></label>)}</div>
            <LandingBar l={leadLanding[`${search.region.id}|${l.lat},${l.lon}`]} compact/>
            <div className="ai-actions"><button className="primary" onClick={()=>onCompare(l)}><Layers size={13}/>{t({ru:'Сравнить в 3D',en:'Compare in 3D',uz:'3D da solishtirish'})}</button><a href={l.satellite} target="_blank" rel="noreferrer"><MapPin size={13}/>{t({ru:'Спутниковый снимок',en:'Satellite image',uz:'Sun’iy yo‘ldosh tasviri'})}</a>{!search.reference.id.includes('@')&&<a href={`/api/tm/report/${search.reference.id}__${search.region.id}?lat=${l.lat}&lon=${l.lon}`} target="_blank" rel="noreferrer" title={t({ru:'Краткий отчёт: оба участка, показатели, источники и статус проверки. Можно сохранить в PDF через браузер.',en:'A short report with both areas, metrics, sources and review status. Save it as a PDF from your browser.',uz:'Qisqa hisobot: ikkala hudud, raqamlar, manbalar va tekshiruv holati. Brauzerdan PDF qilib saqlash mumkin.'})}><FileText size={13}/>{t({ru:'Отчёт',en:'Report',uz:'Hisobot'})}</a>}</div></div>}
        </li>)}</ol>
        {search.known_sites.map(k=><p key={k.site} className="ai-known">{t({ru:`Известный аналог — ${k.name}: место ${k.rank} из ${k.of} (верхние ${k.top_percent}%), оценка ${nf(k.score)}.`,en:`Known analogue — ${k.name}: rank ${k.rank} of ${k.of} (top ${k.top_percent}%), score ${nf(k.score)}.`,uz:`Ma’lum analog — ${k.name}: ${k.of} hududdan ${k.rank}-o‘rin (top ${k.top_percent}%), ball ${nf(k.score)}.`})}</p>)}
        <small className="ai-fine">{t({ru:'Участки также отмечены на карте Земли. Это кандидаты: сходство необходимо проверить по спутниковым снимкам.',en:'The areas are also marked on the Earth map. These are candidates; the similarities need human review of satellite images.',uz:'Hududlar Yer xaritasida ham belgilandi. Bular nomzodlar; o‘xshashlikni inson sun’iy yo‘ldosh tasvirida tekshirishi kerak.'})}</small></section>}
    </div>
    <form className="ai-input" onSubmit={e=>{e.preventDefault();ask(input)}}>
      <textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(input)}}} rows={2} maxLength={600} placeholder={t({ru:'Напишите на любом языке…',en:'Write in any language…',uz:'Istalgan tilda yozing…'})} aria-label={t({ru:'Вопрос ИИ-помощнику',en:'Question for the AI assistant',uz:'AI yordamchiga savol'})} disabled={busy||!ov?.ai_available}/>
      <button type="submit" disabled={busy||!ov?.ai_available||!input.trim()} aria-label={t({ru:'Отправить',en:'Send',uz:'Yuborish'})}><Send size={15}/></button>
    </form>
    {ov&&<div className="ai-manual"><span>{t({ru:'Или выберите напрямую',en:'Or select directly',uz:'Yoki to‘g‘ridan-to‘g‘ri tanlang'})}</span>
      <select value={manualRef} onChange={e=>setManualRef(e.target.value)} aria-label={t({ru:'Эталонный участок',en:'Reference area',uz:'Namuna hudud'})}>{ov.references.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
      <select value={manualRegion} onChange={e=>setManualRegion(e.target.value)} aria-label={t({ru:'Регион на Земле',en:'Earth region',uz:'Yerdagi hudud'})}>{ov.regions.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
      <button onClick={manual} disabled={busy||!manualRef||!manualRegion}><Search size={13}/>{t({ru:'Показать',en:'Show',uz:'Ko‘rsatish'})}</button></div>}
    <div className="ai-foot"><Orbit size={12}/>{t({ru:'ИИ выбирает инструменты и объясняет результаты. Каждую оценку рассчитывает алгоритм.',en:'AI selects tools and explains the results. Every score is calculated by the algorithm.',uz:'AI vositalarni tanlaydi va natijalarni tushuntiradi. Har bir ballni algoritm hisoblaydi.'})}</div>
  </aside>;
}
