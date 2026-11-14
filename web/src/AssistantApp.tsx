import {Suspense,lazy,useEffect,useMemo,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {ArrowUpRight,Bot,Check,Compass,Globe2,LoaderCircle,MapPin,Mountain,Orbit,Search,Send,ShieldCheck,Sparkles,TriangleAlert,X} from 'lucide-react';
import './explorer.css';
import './assistant.css';

const CompareTerrain=lazy(()=>import('./components/CompareTerrain'));

type Summary={p5:number|null;median:number|null;p95:number|null;count:number};
type MapMeta={kind:'polar'|'equirect';image:string;marker:{x:number;y:number};box:{x0:number;y0:number;x1:number;y1:number};caption:string};
type Reference={id:string;name:string;body:'mars'|'moon';center:{lat:number;lon:number};dataset?:string;window_km:number;grid_m:number;metric_summary?:Record<'slope_deg'|'relief_m'|'tri_m',Summary>;map?:MapMeta|null;map_error?:string;note?:string};
type Lead={lat:number;lon:number;rank?:number;overall_A:number;overall_B?:number;slope_deg?:number;relief_m?:number;tri_m?:number;slope_median?:number;tri_median?:number;satellite?:string};
type Known={site:string;name:string;rank:number;of:number;top_percent:number;score:number;nearest_window:{lat:number;lon:number}};
type SearchView={reference:{id:string;name:string};region:{id:string;name:string;bbox:[number,number,number,number]};counts:{windows:number;scored:number;water:number;nodata:number};score_distribution:{max:number;p90:number;median:number;min:number}|null;top:Lead[];known_sites:Known[];windows:[number,number,number][];stride_km:number;reviews:Record<string,{verdict:string;note:string}>};
type Step={kind:'reference';reference:Reference}|{kind:'search';search_id:string};
type Message={role:'user'|'assistant';content:string;unverified?:string[];steps?:Step[];error?:boolean};
type Pending={id:string;name:string;body:string;state:string};
type Overview={references:Reference[];pending_references?:Pending[];regions:{id:string;name:string}[];searches:{id:string;reference:{id:string;name:string};region:{id:string;name:string}}[];ai_available:boolean};

const EXAMPLES=[
  'Find a place on Earth whose terrain matches LOLA’s Mons Mouton plateau on the Moon',
  'Which places in western Uzbekistan look like Opportunity’s Meridiani Planum?',
  'Find Gale crater analogs around MDRS in Utah',
  'Oydagi LOLA relyefiga mos joyni Yerdan topib ber',
];
const nf=(v:number|null|undefined,d=2)=>v===null||v===undefined||!Number.isFinite(v)?'—':v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const coord=(p:{lat:number;lon:number})=>`${Math.abs(p.lat).toFixed(3)}° ${p.lat<0?'S':'N'}, ${Math.abs(p.lon).toFixed(3)}° ${p.lon<0?'W':'E'}`;
const leadKey=(l:Lead)=>`${l.lat.toFixed(5)},${l.lon.toFixed(5)}`;
async function api<T>(url:string,init?:RequestInit):Promise<T>{const r=await fetch(url,init);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof j.detail==='string'?j.detail:`Server error ${r.status}`);return j as T}

const RAMP=['#1d3b2b','#3e6b43','#7da35c','#c3d27a','#eef0b6'];
function rampColor(t:number){t=Math.max(0,Math.min(1,t));const x=t*(RAMP.length-1),i=Math.min(Math.floor(x),RAMP.length-2),f=x-i;const a=RAMP[i].match(/\w\w/g)!.map(h=>parseInt(h,16)),b=RAMP[i+1].match(/\w\w/g)!.map(h=>parseInt(h,16));return `rgb(${a.map((v,k)=>Math.round(v+(b[k]-v)*f)).join(',')})`}

const ZOOM=6; // Mars: show ~60° x 30° of the global map around the site
function ReferenceMap({meta,body}:{meta:MapMeta;body:'mars'|'moon'}){
  const {marker:m,box:b}=meta;
  const z=meta.kind==='equirect'?ZOOM:1;
  const clamp=(v:number)=>z===1?.5:Math.min(Math.max(v,1/(2*z)),1-1/(2*z));
  const cx=clamp(m.x),cy=clamp(m.y);
  const fx=(x:number)=>z===1?x:.5+(x-cx)*z,fy=(y:number)=>z===1?y:.5+(y-cy)*z;
  const img=z===1?undefined:{position:'absolute' as const,width:`${z*100}%`,height:`${z*100}%`,maxWidth:'none',left:`${(.5-cx*z)*100}%`,top:`${(.5-cy*z)*100}%`};
  return <figure className={`ref-map ${meta.kind}`}>
    <div className="ref-map-frame">
      <img src={meta.image} alt={meta.caption} style={img}/>
      <span className="ref-box" style={{left:`${fx(b.x0)*100}%`,top:`${fy(b.y0)*100}%`,width:`${Math.max((fx(b.x1)-fx(b.x0))*100,1.2)}%`,height:`${Math.max((fy(b.y1)-fy(b.y0))*100,1.2)}%`}}/>
      <span className={`ref-pin ${body}`} style={{left:`${fx(m.x)*100}%`,top:`${fy(m.y)*100}%`}}/>
    </div>
    <figcaption>{meta.kind==='equirect'?`${meta.caption} · 60° × 30° around the site`:meta.caption}</figcaption>
  </figure>;
}

function LeadsMap({view,selected,onSelect}:{view:SearchView;selected:number;onSelect:(i:number)=>void}){
  const el=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),layer=useRef<L.LayerGroup|null>(null);
  useEffect(()=>{if(!el.current||map.current)return;
    const m=L.map(el.current,{preferCanvas:true,zoomControl:true,attributionControl:true});
    const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:17,attribution:'Imagery © Esri, Maxar, Earthstar Geographics'}).addTo(m);
    const osm=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'© OpenStreetMap contributors'});
    L.control.layers({'Satellite':sat,'Map':osm},{}, {position:'topright'}).addTo(m);L.control.scale({imperial:false}).addTo(m);
    map.current=m;return()=>{m.remove();map.current=null}},[]);
  useEffect(()=>{const m=map.current;if(!m)return;layer.current?.remove();const g=L.layerGroup().addTo(m);layer.current=g;
    const s=view.windows.map(w=>w[2]).sort((a,b)=>a-b);const lo=s.length?Math.floor(s[Math.floor(s.length*.02)]*20)/20:0,hi=s.length?Math.ceil(s[s.length-1]*20)/20:1,span=Math.max(hi-lo,.1);
    const dLat=view.stride_km/111.32;
    for(const [lat,lon,v] of view.windows){const dLon=view.stride_km/(111.32*Math.cos(lat*Math.PI/180));
      L.rectangle([[lat-dLat/2,lon-dLon/2],[lat+dLat/2,lon+dLon/2]],{stroke:false,fillColor:rampColor((v-lo)/span),fillOpacity:.5}).bindTooltip(`similarity ${v.toFixed(3)}`,{sticky:true}).addTo(g)}
    view.top.forEach((t,i)=>{const rv=view.reviews[leadKey(t)];L.marker([t.lat,t.lon],{icon:L.divIcon({className:'',html:`<div class="tm-pin ${rv?.verdict??''} ${i===selected?'active':''}">${i+1}</div>`,iconSize:[26,26],iconAnchor:[13,13]})}).on('click',()=>onSelect(i)).addTo(g)});
    for(const k of view.known_sites)L.marker([k.nearest_window.lat,k.nearest_window.lon],{icon:L.divIcon({className:'',html:'<div class="tm-known"></div>',iconSize:[14,14],iconAnchor:[7,7]})}).bindTooltip(`${k.name}: rank ${k.rank} of ${k.of}`).addTo(g);
    const [w,so,e,n]=view.region.bbox;m.fitBounds([[so,w],[n,e]],{padding:[10,10]});
  },[view,selected,onSelect]);
  useEffect(()=>{const m=map.current,t=view.top[selected];if(m&&t)m.flyTo([t.lat,t.lon],Math.max(m.getZoom(),9),{duration:.8})},[selected,view]);
  return <div className="leads-map" ref={el}/>;
}

export default function AssistantApp(){
  const [ov,setOv]=useState<Overview|null>(null),[conn,setConn]=useState<'loading'|'ready'|'error'>('loading');
  const [messages,setMessages]=useState<Message[]>([]),[input,setInput]=useState(''),[busy,setBusy]=useState(false);
  const [reference,setReference]=useState<Reference|null>(null),[view,setView]=useState<SearchView|null>(null),[selected,setSelected]=useState(0);
  const [compare,setCompare]=useState<Lead|null>(null),[manualRef,setManualRef]=useState(''),[manualRegion,setManualRegion]=useState('');
  const thread=useRef<HTMLDivElement>(null);
  useEffect(()=>{api<Overview>('/api/tm/overview').then(o=>{setOv(o);setConn('ready');setManualRef(o.references[0]?.id??'');setManualRegion(o.regions.find(r=>r.id==='uzbekistan_west')?.id??o.regions[0]?.id??'')}).catch(()=>setConn('error'))},[]);
  useEffect(()=>{thread.current?.scrollTo({top:thread.current.scrollHeight,behavior:'smooth'})},[messages,busy]);

  const showReference=async(id:string)=>{const r=await api<Reference>(`/api/tm/reference/${id}`);setReference(r);setManualRef(id);setView(v=>v&&v.reference.id===id?v:null);return r};
  const showSearch=async(id:string)=>{const v=await api<SearchView>(`/api/tm/search/${id}`);setView(v);setSelected(0);setManualRegion(v.region.id);return v};
  const ask=async(q:string)=>{q=q.trim();if(!q||busy)return;setInput('');const history=messages.map(m=>({role:m.role,content:m.content}));setMessages(m=>[...m,{role:'user',content:q}]);setBusy(true);
    try{const r=await api<{answer:string;unverified_numbers:string[];steps:any[]}>('/api/tm/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});
      const steps:Step[]=[];
      for(const st of r.steps){if(st.kind==='reference'){const ref=await showReference(st.reference.id);steps.push({kind:'reference',reference:ref})}else if(st.kind==='search'){await showSearch(st.search_id);steps.push({kind:'search',search_id:st.search_id})}}
      setMessages(m=>[...m,{role:'assistant',content:r.answer,unverified:r.unverified_numbers,steps}]);
    }catch(e){setMessages(m=>[...m,{role:'assistant',content:(e as Error).message,error:true}])}finally{setBusy(false)}};
  const manual=async()=>{if(!manualRef)return;setBusy(true);try{await showReference(manualRef);const id=`${manualRef}__${manualRegion}`;if(ov?.searches.some(s=>s.id===id))await showSearch(id);else{setView(null);setMessages(m=>[...m,{role:'assistant',content:`No search has been run yet for this pair. Run: python -m terramind search --reference ${manualRef} --region ${manualRegion}`,error:true}])}}catch(e){setMessages(m=>[...m,{role:'assistant',content:(e as Error).message,error:true}])}finally{setBusy(false)}};
  const review=async(l:Lead,verdict:'accepted'|'rejected'|'clear')=>{if(!view)return;const note=verdict==='rejected'?(prompt('Why is this lead rejected? (e.g. open-pit mine, fields, town)')??''):'';
    try{const r=await api<{reviews:SearchView['reviews']}>('/api/tm/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({search_id:`${view.reference.id}__${view.region.id}`,lat:l.lat,lon:l.lon,verdict,note})});setView({...view,reviews:r.reviews})}catch(e){alert((e as Error).message)}};
  const lead=view?.top[selected];
  const refBody=reference?.body??'mars';
  const ms=reference?.metric_summary;
  const stageStep=reference?(view?2:1):0;
  const selectLead=useMemo(()=>(i:number)=>setSelected(i),[]);

  return <div className="explorer assistant">
    <header className="science-header">
      <a className="science-brand" href="/"><Mountain size={30} strokeWidth={1.4}/><span>TerraMind<span className="science-ai">AI</span></span><i/><small>EARTH ANALOGS FOR MARS AND THE MOON</small></a>
      <nav><span className="nav-active"><Sparkles size={15}/>AI Assistant</span><a href="/?view=explorer"><Compass size={15}/>Global Explorer</a><a href="https://github.com/AkramovFozil/terramind-ai" target="_blank" rel="noreferrer">Method & data<ArrowUpRight size={13}/></a></nav>
      <span className={`backend-state ${conn}`}><i/>{conn==='ready'?(ov?.ai_available?'AI READY':'AI KEY MISSING'):conn==='loading'?'CONNECTING':'SERVER OFFLINE'}</span>
    </header>
    <div className="assistant-grid">
      <section className="chat-col" aria-label="Conversation">
        <div className="chat-intro">
          <p className="science-kicker">ASK TERRAMIND</p>
          <h1>Find Earth’s twin of a site on <em>Mars</em> or the <em>Moon</em>.</h1>
          <p>Name a site or a NASA dataset. The AI marks it on its map, the algorithm scans Earth with the same method, and every number in the answer is checked against the results.</p>
        </div>
        <div className="chat-thread" ref={thread}>
          {!messages.length&&<div className="examples">{EXAMPLES.map(q=><button key={q} onClick={()=>ask(q)} disabled={busy||!ov?.ai_available}><Sparkles size={13}/>{q}</button>)}</div>}
          {messages.map((m,i)=><div key={i} className={`bubble ${m.role} ${m.error?'error':''}`}>
            {m.role==='assistant'&&<span className="who"><Bot size={13}/>TerraMind</span>}
            <p>{m.content}</p>
            {m.steps&&m.steps.length>0&&<ol className="step-trail">{m.steps.map((s,k)=><li key={k}>{s.kind==='reference'?<><Orbit size={12}/>Marked {s.reference.name}</>:<><Search size={12}/>Scanned Earth windows</>}</li>)}</ol>}
            {m.role==='assistant'&&!m.error&&(m.unverified&&m.unverified.length?<span className="verify warn"><TriangleAlert size={12}/>Not in TerraMind’s results — do not trust: {m.unverified.join(', ')}</span>:<span className="verify ok"><ShieldCheck size={12}/>Every number matches TerraMind’s computed results</span>)}
          </div>)}
          {busy&&<div className="bubble assistant thinking"><LoaderCircle size={14} className="rotating"/>Working: reading the reference, scanning Earth…</div>}
        </div>
        <form className="chat-input" onSubmit={e=>{e.preventDefault();ask(input)}}>
          <textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(input)}}} rows={2} maxLength={600} placeholder={ov?.ai_available===false?'Add OPENROUTER_API_KEY to .env to chat — or use the direct mode below':'Ask in any language…'} disabled={busy}/>
          <button type="submit" disabled={busy||!input.trim()} aria-label="Send"><Send size={16}/></button>
        </form>
        {ov&&<div className="manual">
          <span>Or choose directly</span>
          <select value={manualRef} onChange={e=>setManualRef(e.target.value)}>{ov.references.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
          <select value={manualRegion} onChange={e=>setManualRegion(e.target.value)}>{ov.regions.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
          <button onClick={manual} disabled={busy}>Show</button>
        </div>}
      </section>

      <section className="stage" aria-label="Results">
        <ol className="stage-steps">
          <li className={stageStep>=1?'done':stageStep===0?'next':''}><span>1</span>Reference marked</li>
          <li className={stageStep>=2?'done':stageStep===1?'next':''}><span>2</span>Earth scanned</li>
          <li className={compare?'done':stageStep===2?'next':''}><span>3</span>Compared in 3D</li>
        </ol>
        {!reference&&<div className="stage-empty">
          <Globe2 size={40} strokeWidth={1.2}/>
          <h2>Ask a question to begin</h2>
          <p>Try “Find a place on Earth that matches the Moon’s Mons Mouton plateau”. References available: {ov?.references.map(r=>r.name).join(' · ')||'—'}.</p>
          {ov?.pending_references?.map(p=><p key={p.id} className="pending-ref"><TriangleAlert size={13}/>{p.name} is {p.state.replace('_',' ')}. Approve its window first: <code>python -m terramind approve --site {p.id}</code></p>)}
        </div>}
        {reference&&<article className={`stage-card ref-card ${reference.body}`}>
          <header><span className={`body-tag ${reference.body}`}>{reference.body==='moon'?'MOON':'MARS'}</span><div><h2>{reference.name}</h2><span>{coord(reference.center)} · {reference.dataset??''}</span></div></header>
          <div className="ref-layout">
            {reference.map?<ReferenceMap meta={reference.map} body={refBody}/>:<div className="ref-map-missing"><Orbit size={30} strokeWidth={1.2}/><p>{coord(reference.center)}</p><small>{reference.map_error??'Map not available'}</small></div>}
            <figure className="ref-window"><div><img src={`/api/tm/window-image/${reference.id}.png`} alt={`Shaded relief of the ${reference.window_km} km window`} onError={e=>{(e.currentTarget.parentElement as HTMLElement).style.display='none'}}/><span>{reference.window_km} km</span></div><figcaption>The scored window · shaded relief from {reference.body==='moon'?'LOLA':'MOLA'}, {reference.grid_m} m grid</figcaption></figure>
            <div className="ref-metrics">
              <p className="science-kicker">MEASURED TERRAIN · {reference.window_km} KM WINDOW · {reference.grid_m} M GRID</p>
              <dl>
                <div><dt>Median slope</dt><dd>{nf(ms?.slope_deg?.median,1)}°</dd></div>
                <div><dt>Median roughness (TRI)</dt><dd>{nf(ms?.tri_m?.median,1)} m</dd></div>
                <div><dt>Relief, 5–95%</dt><dd>{nf(ms?.relief_m?.p5,0)} … {nf(ms?.relief_m?.p95,0)} m</dd></div>
              </dl>
              <p className="fine">The white square on the map is this window. A person approved it on its quick-look before any similarity score existed.</p>
            </div>
          </div>
        </article>}
        {view&&<article className="stage-card earth-card">
          <header><span className="body-tag earth">EARTH</span><div><h2>{view.region.name}</h2><span>{view.counts.scored.toLocaleString('en-US')} windows scored · {view.counts.water} water excluded · median {nf(view.score_distribution?.median)} · best {nf(view.score_distribution?.max)}</span></div></header>
          <div className="earth-layout">
            <LeadsMap view={view} selected={selected} onSelect={selectLead}/>
            <ol className="lead-list">{view.top.slice(0,8).map((l,i)=>{const rv=view.reviews[leadKey(l)];return <li key={leadKey(l)} className={`${i===selected?'selected':''} ${rv?.verdict??''}`}>
              <button className="lead-main" onClick={()=>setSelected(i)}><span className="lead-rank">{i+1}</span><span className="lead-coord">{coord(l)}</span><strong>{nf(l.overall_A)}</strong></button>
              {i===selected&&<div className="lead-detail">
                <div className="lead-bars">{(['slope_deg','relief_m','tri_m'] as const).map(k=><label key={k}><span>{k==='slope_deg'?'Slope':k==='relief_m'?'Relief':'Roughness'}</span><i><b style={{width:`${(l[k]??0)*100}%`}}/></i><em>{nf(l[k])}</em></label>)}</div>
                {rv?.note&&<p className="fine">Note: {rv.note}</p>}
                <div className="lead-actions">
                  <button className="primary" onClick={()=>setCompare(l)}><Mountain size={13}/>Compare in 3D</button>
                  <a href={l.satellite} target="_blank" rel="noreferrer"><MapPin size={13}/>Satellite</a>
                  <button onClick={()=>review(l,'accepted')}><Check size={13}/>Accept</button>
                  <button onClick={()=>review(l,'rejected')}><X size={13}/>Reject</button>
                </div>
              </div>}
            </li>})}</ol>
          </div>
          {view.known_sites.map(k=><p className="known" key={k.site}>Known analog in this region — {k.name}: its window ranks {k.rank} of {k.of} (top {k.top_percent}%), score {nf(k.score)}.</p>)}
          <p className="fine">Leads come from TerraMind’s algorithm (NASA SRTM, 25 km windows, same method as the sites). A lead becomes an analog only after a person checks it on satellite imagery.</p>
        </article>}
      </section>
    </div>
    {compare&&reference&&view&&<div className="science-modal" role="dialog" aria-modal="true" onClick={e=>{if(e.target===e.currentTarget)setCompare(null)}}>
      <div className="science-dialog compare-dialog">
        <div className="dialog-header"><div><p className="science-kicker">SAME SCALE · SAME GRID · MEASURED DEMs</p><h2>{reference.name} vs Earth lead {selected+1}</h2></div><button onClick={()=>setCompare(null)} aria-label="Close"><X size={18}/></button></div>
        <Suspense fallback={<div className="terrain-loading"><span className="science-spinner"/>Loading terrain…</div>}>
          <CompareTerrain marsUrl={`/api/tm/terrain/site/${reference.id}`} earthUrl={`/api/tm/terrain/point?region=${view.region.id}&lat=${compare.lat}&lon=${compare.lon}`} score={compare.overall_A*100} leftTitle={reference.body==='moon'?'MOON':'MARS'} leftSub={`${reference.name} · ${reference.dataset??''}`} rightSub={`${coord(compare)} · NASA SRTM 463 m`}/>
        </Suspense>
      </div>
    </div>}
  </div>;
}
