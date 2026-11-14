import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {Canvas,useThree,type ThreeEvent} from '@react-three/fiber';
import {OrbitControls} from '@react-three/drei';
import * as THREE from 'three';
import type {Match,TerrainData} from '../science-types';

type Layer='relief'|'slope_deg'|'roughness_m';
type Align={angle:number;mirrored:boolean};
type Probe={x:number;z:number};
type Sample={elevation:number;relief:number;slope:number|null;roughness:number|null};
type Rig={camera:THREE.Camera;controls:{target:THREE.Vector3;update:()=>void}|null;invalidate:()=>void};

const SIZE=100;
const NO_ALIGN:Align={angle:0,mirrored:false};
const LAYERS:{id:Layer;name:string;unit:string;hint:string}[]=[
  {id:'relief',name:'Relyef',unit:'m',hint:'Balandlik − doira medianasi'},
  {id:'slope_deg',name:'Qiyalik',unit:'°',hint:'Horn usuli, 463 m katakda'},
  {id:'roughness_m',name:'Notekislik',unit:'m',hint:'Qiyalik olib tashlangach qolgan g‘adir-budurlik (3×3 tekislikdan RMS chetlanish)'},
];
const RAMPS:Record<Layer,string[]>={
  relief:['#27408b','#7fa9d4','#efe9d6','#d8935f','#8a2a1c'],
  slope_deg:['#1c3328','#5f9a63','#e6d268','#e0823a','#b0241d'],
  roughness_m:['#17152b','#553a8a','#bd5788','#f09f4a','#fbeeb2'],
};
const rampColors=Object.fromEntries(Object.entries(RAMPS).map(([k,v])=>[k,v.map(c=>new THREE.Color(c))])) as Record<Layer,THREE.Color[]>;
function ramp(layer:Layer,t:number,out:THREE.Color){const stops=rampColors[layer];const p=Math.min(Math.max(t,0),1)*(stops.length-1);const i=Math.min(Math.floor(p),stops.length-2);return out.copy(stops[i]).lerp(stops[i+1],p-i)}

function layerValue(data:TerrainData,layer:Layer,i:number):number|null{
  if(layer==='relief'){const v=data.elevations[i];return v===null?null:v-data.median_elevation_m}
  return data.layers[layer][i];
}
function percentileRange(datasets:TerrainData[],layer:Layer):[number,number]{
  const values:number[]=[];
  for(const d of datasets)for(let i=0;i<d.elevations.length;i++){if(!d.roi_mask[i])continue;const v=layerValue(d,layer,i);if(v!==null&&Number.isFinite(v))values.push(v)}
  if(!values.length)return [0,1];
  values.sort((a,b)=>a-b);
  const q=(p:number)=>values[Math.min(values.length-1,Math.floor(p*(values.length-1)))];
  if(layer==='relief'){const m=Math.max(Math.abs(q(.02)),Math.abs(q(.98)),1);return [-m,m]}
  return [0,Math.max(q(.98),layer==='slope_deg'?1:.5)];
}
/** Grid offset (metres east, south of centre) -> displayed position, and back. */
function forward(x:number,z:number,a:Align):[number,number]{const c=Math.cos(a.angle),s=Math.sin(a.angle);const rx=x*c-z*s,rz=x*s+z*c;return [a.mirrored?-rx:rx,rz]}
function inverse(x:number,z:number,a:Align):[number,number]{const c=Math.cos(a.angle),s=Math.sin(a.angle);const rx=a.mirrored?-x:x;return [rx*c+z*s,-rx*s+z*c]}
function sampleAt(data:TerrainData,align:Align,probe:Probe,unit:number):Sample|null{
  const [gx,gz]=inverse(probe.x/unit,probe.z/unit,align);
  const col=Math.round(gx/data.pixel_size_m+(data.width-1)/2),row=Math.round(gz/data.pixel_size_m+(data.height-1)/2);
  if(col<0||row<0||col>=data.width||row>=data.height)return null;
  const i=row*data.width+col,elevation=data.elevations[i];
  if(!data.roi_mask[i]||elevation===null)return null;
  return {elevation,relief:elevation-data.median_elevation_m,slope:data.layers.slope_deg[i],roughness:data.layers.roughness_m[i]};
}

function Surface({data,layer,range,exaggeration,align,unit,onProbe}:{data:TerrainData;layer:Layer;range:[number,number];exaggeration:number;align:Align;unit:number;onProbe:(p:Probe|null)=>void}){
  const geometry=useMemo(()=>{
    const {width,height,pixel_size_m,elevations,roi_mask}=data;
    const positions=new Float32Array(width*height*3),colors=new Float32Array(width*height*3),indices:number[]=[];
    const shade=new THREE.Color(),ok=(i:number)=>roi_mask[i]&&elevations[i]!==null;
    for(let row=0;row<height;row++)for(let col=0;col<width;col++){
      const i=row*width+col,elevation=elevations[i]??data.median_elevation_m;
      const [x,z]=forward((col-(width-1)/2)*pixel_size_m,(row-(height-1)/2)*pixel_size_m,align);
      positions.set([x*unit,(elevation-data.median_elevation_m)*unit*exaggeration,z*unit],i*3);
      const v=layerValue(data,layer,i);
      ramp(layer,v===null?0:(v-range[0])/(range[1]-range[0]),shade);
      colors.set([shade.r,shade.g,shade.b],i*3);
      if(row<height-1&&col<width-1){const a=i,b=i+1,c=i+width,d=c+1;if(ok(a)&&ok(c)&&ok(b))indices.push(a,c,b);if(ok(b)&&ok(c)&&ok(d))indices.push(b,c,d)}
    }
    const geo=new THREE.BufferGeometry();
    geo.setAttribute('position',new THREE.BufferAttribute(positions,3));
    geo.setAttribute('color',new THREE.BufferAttribute(colors,3));
    geo.setIndex(indices);geo.computeVertexNormals();return geo;
  },[data,layer,range,exaggeration,align,unit]);
  useEffect(()=>()=>geometry.dispose(),[geometry]);
  const move=(e:ThreeEvent<PointerEvent>)=>{e.stopPropagation();onProbe({x:e.point.x,z:e.point.z})};
  return <mesh geometry={geometry} onPointerMove={move} onPointerOut={()=>onProbe(null)}><meshStandardMaterial vertexColors roughness={.95} metalness={0} side={THREE.DoubleSide}/></mesh>;
}

function Marker({sample,probe,unit,exaggeration}:{sample:Sample|null;probe:Probe|null;unit:number;exaggeration:number}){
  if(!probe||!sample)return null;
  const y=sample.relief*unit*exaggeration;
  return <group position={[probe.x,y,probe.z]}><mesh position={[0,6,0]}><cylinderGeometry args={[.12,.12,12,8]}/><meshBasicMaterial color="#ffffff"/></mesh><mesh><sphereGeometry args={[.9,16,12]}/><meshBasicMaterial color="#ffffff"/></mesh></group>;
}

function RigSync({id,rigs,driver}:{id:string;rigs:React.MutableRefObject<Record<string,Rig>>;driver:React.MutableRefObject<string|null>}){
  const {camera,invalidate}=useThree();
  const controls=useRef<any>(null);
  useEffect(()=>{rigs.current[id]={camera,controls:controls.current,invalidate};return()=>{delete rigs.current[id]}},[id,camera,invalidate,rigs]);
  const change=()=>{
    if(driver.current!==id)return;
    for(const [other,rig] of Object.entries(rigs.current)){
      if(other===id||!rig.controls||!controls.current)continue;
      rig.camera.position.copy(camera.position);rig.controls.target.copy(controls.current.target);rig.controls.update();rig.invalidate();
    }
  };
  return <OrbitControls ref={controls} makeDefault enableDamping={false} minDistance={25} maxDistance={260} maxPolarAngle={Math.PI*.49} onStart={()=>{driver.current=id}} onChange={change}/>;
}

function Panel({id,title,subtitle,data,layer,range,exaggeration,align,unit,floor,probe,sample,onProbe,rigs,driver}:{id:string;floor:number;title:string;subtitle:string;data:TerrainData;layer:Layer;range:[number,number];exaggeration:number;align:Align;unit:number;probe:Probe|null;sample:Sample|null;onProbe:(p:Probe|null)=>void;rigs:React.MutableRefObject<Record<string,Rig>>;driver:React.MutableRefObject<string|null>}){
  return <div className={`compare-panel compare-${id}`}>
    <div className="compare-tag"><i/><strong>{title}</strong><span>{subtitle}</span></div>
    <Canvas frameloop="demand" dpr={[1,1.5]} camera={{position:[70,62,88],fov:42,near:.1,far:1200}} gl={{antialias:true,powerPreference:'default'}}>
      <color attach="background" args={['#101615']}/>
      <hemisphereLight args={['#f4efdf','#2c3331',2.1]}/>
      <directionalLight position={[-70,90,35]} intensity={2.6} color="#fff1d6"/>
      <Surface data={data} layer={layer} range={range} exaggeration={exaggeration} align={align} unit={unit} onProbe={onProbe}/>
      <Marker sample={sample} probe={probe} unit={unit} exaggeration={exaggeration}/>
      <gridHelper args={[SIZE*1.3,13,'#46534b','#222c27']} position={[0,floor,0]}/>
      <RigSync id={id} rigs={rigs} driver={driver}/>
    </Canvas>
  </div>;
}

const fmt=(v:number|null|undefined,d=1)=>v===null||v===undefined||!Number.isFinite(v)?'—':v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const signed=(v:number|null,d=1)=>v===null||!Number.isFinite(v)?'—':`${v>0?'+':''}${fmt(v,d)}`;

export default function CompareTerrain({marsUrl,earthUrl,match,score,leftTitle='MARS',leftSub,rightSub}:{marsUrl:string;earthUrl:string;match?:Match;score?:number;leftTitle?:string;leftSub?:string;rightSub?:string}){
  const leftName=leftTitle==='MARS'?'Mars':leftTitle.charAt(0)+leftTitle.slice(1).toLowerCase();
  const [mars,setMars]=useState<TerrainData|null>(null),[earth,setEarth]=useState<TerrainData|null>(null),[error,setError]=useState('');
  const [layer,setLayer]=useState<Layer>('relief'),[exaggeration,setExaggeration]=useState(5),[aligned,setAligned]=useState(true);
  const [probe,setProbe]=useState<Probe|null>(null);
  const rigs=useRef<Record<string,Rig>>({}),driver=useRef<string|null>(null);
  useEffect(()=>{
    const controller=new AbortController();setMars(null);setEarth(null);setError('');
    const load=(url:string)=>fetch(url,{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error('Relyef ma’lumotini olishda xato.');return r.json() as Promise<TerrainData>}).then(d=>{if(!d.measured_dem||!d.layers)throw new Error('O‘lchangan DEM qatlamlari topilmadi. Serverni yangilang.');return d});
    Promise.all([load(marsUrl),load(earthUrl)]).then(([m,e])=>{setMars(m);setEarth(e)}).catch(e=>{if(e.name!=='AbortError')setError(e.message)});
    return()=>controller.abort();
  },[marsUrl,earthUrl]);
  // The matcher rotates Mars counter-clockwise by rotation_deg (after an optional mirror) to fit Earth,
  // so Earth is turned clockwise by the same angle, then mirrored, to sit in the Mars orientation.
  const earthAlign=useMemo<Align>(()=>aligned&&match?{angle:match.rotation_deg*Math.PI/180,mirrored:match.mirrored}:NO_ALIGN,[aligned,match]);
  const range=useMemo<[number,number]>(()=>mars&&earth?percentileRange([mars,earth],layer):[0,1],[mars,earth,layer]);
  const onProbe=useCallback((p:Probe|null)=>setProbe(p),[]);
  const resetView=()=>{for(const rig of Object.values(rigs.current)){rig.camera.position.set(70,62,88);rig.controls?.target.set(0,0,0);rig.controls?.update();rig.invalidate()}};
  const topView=()=>{for(const rig of Object.values(rigs.current)){rig.camera.position.set(0,150,.01);rig.controls?.target.set(0,0,0);rig.controls?.update();rig.invalidate()}};
  if(error)return <div className="terrain-loading error-message">{error}</div>;
  if(!mars||!earth)return <div className="terrain-loading"><span className="science-spinner"/>Ikkala sayyoraning o‘lchangan relyefi yuklanmoqda…</div>;
  const unit=SIZE/(Math.max(mars.width,mars.height)*mars.pixel_size_m);
  const ms=probe?sampleAt(mars,NO_ALIGN,probe,unit):null,es=probe?sampleAt(earth,earthAlign,probe,unit):null;
  const floor=Math.min(mars.roi_min_elevation_m-mars.median_elevation_m,earth.roi_min_elevation_m-earth.median_elevation_m)*unit*exaggeration-2;
  const info=LAYERS.find(l=>l.id===layer)!;
  const gradient=`linear-gradient(90deg,${RAMPS[layer].join(',')})`;
  const stat=(d:TerrainData,key:'slope_deg'|'roughness_m')=>d.layer_stats[key];
  const diff=(a:number|null|undefined,b:number|null|undefined)=>a===null||a===undefined||b===null||b===undefined?null:b-a;
  return <div className="compare-view">
    <div className="compare-toolbar">
      <div className="compare-layers" role="group" aria-label="Ko‘rsatiladigan qatlam">{LAYERS.map(l=><button key={l.id} aria-pressed={layer===l.id} title={l.hint} onClick={()=>setLayer(l.id)}>{l.name}</button>)}</div>
      <div className="compare-legend" title={info.hint}><span>{fmt(range[0],layer==='relief'?0:1)}{info.unit}</span><i style={{background:gradient}}/><span>{fmt(range[1],layer==='relief'?0:1)}{info.unit}</span><em>ikkala sayyora uchun bitta shkala</em></div>
      <label className="compare-option"><input type="checkbox" checked={aligned} onChange={e=>setAligned(e.target.checked)} disabled={!match}/>Yerni {leftName}ga moslab burish{match?` (${match.rotation_deg}°${match.mirrored?', ko‘zgu':''})`:''}</label>
      <label className="compare-option">Balandlik masshtabi <select value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}><option value={1}>1× — haqiqiy nisbat</option><option value={3}>3× — bo‘rttirilgan</option><option value={5}>5× — bo‘rttirilgan</option><option value={10}>10× — bo‘rttirilgan</option></select></label>
      <button className="compare-view-button" onClick={topView}>Tepadan</button><button className="compare-view-button" onClick={resetView}>3D</button>
    </div>
    <div className="compare-panels">
      <Panel id="mars" title={leftTitle} subtitle={leftSub??`${fmt(mars.center.lat,3)}°, ${fmt(mars.center.lon,3)}° · MOLA 463 m`} data={mars} layer={layer} range={range} exaggeration={exaggeration} align={NO_ALIGN} unit={unit} floor={floor} probe={probe} sample={ms} onProbe={onProbe} rigs={rigs} driver={driver}/>
      <Panel id="earth" title="YER" subtitle={`${rightSub??`${fmt(earth.center.lat,3)}°, ${fmt(earth.center.lon,3)}° · Copernicus 463 m`}${score===undefined?'':` · ${fmt(score)}/100`}`} data={earth} layer={layer} range={range} exaggeration={exaggeration} align={earthAlign} unit={unit} floor={floor} probe={probe} sample={es} onProbe={onProbe} rigs={rigs} driver={driver}/>
    </div>
    <div className="compare-readout">
      <table><thead><tr><th>{probe?'Kursor ostidagi nuqta':'Butun doira (25 km)'}</th><th>{probe?'Balandlik':'Balandlik oralig‘i'}</th><th>{probe?'Relyef':'Relyef amplitudasi'}</th><th>Qiyalik{probe?'':' · mediana / p95'}</th><th>Notekislik{probe?'':' · mediana / p95'}</th></tr></thead>
        <tbody>{probe?<>
          <tr className="row-mars"><td><i/>{leftName}</td><td>{fmt(ms?.elevation,0)} m</td><td>{signed(ms?.relief??null,0)} m</td><td>{fmt(ms?.slope,2)}°</td><td>{fmt(ms?.roughness,2)} m</td></tr>
          <tr className="row-earth"><td><i/>Yer</td><td>{fmt(es?.elevation,0)} m</td><td>{signed(es?.relief??null,0)} m</td><td>{fmt(es?.slope,2)}°</td><td>{fmt(es?.roughness,2)} m</td></tr>
          <tr className="row-diff"><td>Farq (Yer − {leftName})</td><td>—</td><td>{signed(diff(ms?.relief,es?.relief),0)} m</td><td>{signed(diff(ms?.slope,es?.slope),2)}°</td><td>{signed(diff(ms?.roughness,es?.roughness),2)} m</td></tr>
        </>:<>
          <tr className="row-mars"><td><i/>{leftName}</td><td>{fmt(mars.roi_min_elevation_m,0)} … {fmt(mars.roi_max_elevation_m,0)} m</td><td>{fmt(mars.roi_max_elevation_m-mars.roi_min_elevation_m,0)} m</td><td>{fmt(stat(mars,'slope_deg').median,2)}° / {fmt(stat(mars,'slope_deg').p95,2)}°</td><td>{fmt(stat(mars,'roughness_m').median,2)} / {fmt(stat(mars,'roughness_m').p95,2)} m</td></tr>
          <tr className="row-earth"><td><i/>Yer</td><td>{fmt(earth.roi_min_elevation_m,0)} … {fmt(earth.roi_max_elevation_m,0)} m</td><td>{fmt(earth.roi_max_elevation_m-earth.roi_min_elevation_m,0)} m</td><td>{fmt(stat(earth,'slope_deg').median,2)}° / {fmt(stat(earth,'slope_deg').p95,2)}°</td><td>{fmt(stat(earth,'roughness_m').median,2)} / {fmt(stat(earth,'roughness_m').p95,2)} m</td></tr>
          <tr className="row-diff"><td>Farq (Yer − {leftName})</td><td>—</td><td>{signed((earth.roi_max_elevation_m-earth.roi_min_elevation_m)-(mars.roi_max_elevation_m-mars.roi_min_elevation_m),0)} m</td><td>{signed(diff(stat(mars,'slope_deg').median,stat(earth,'slope_deg').median),2)}°</td><td>{signed(diff(stat(mars,'roughness_m').median,stat(earth,'roughness_m').median),2)} m</td></tr>
        </>}</tbody></table>
      <p>{probe?'Oq belgi ikkala sayyorada bir xil (moslashtirilgan) nuqtani ko‘rsatadi.':'Sichqonchani relyef ustiga olib boring: ikkala sayyoradagi mos nuqtaning aniq qiymatlari chiqadi.'} Kameralar sinxron. Qiymatlar 463 m katakdagi haqiqiy DEM o‘lchovlari; ranglar tanlangan qatlamni ko‘rsatadi.</p>
    </div>
  </div>;
}
