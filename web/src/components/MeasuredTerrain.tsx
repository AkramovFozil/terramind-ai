import {useUiCopy} from '../ui-copy';
import {useI18n} from '../i18n';
import {Suspense,lazy,useEffect,useMemo,useState} from 'react';
import {Layers,Rocket} from 'lucide-react';
import {Canvas} from '@react-three/fiber';
import {OrbitControls} from '@react-three/drei';
import * as THREE from 'three';
import type {TerrainData} from '../science-types';
const MissionPlacement=lazy(()=>import('./mission/MissionPlacement'));
type TerrainMode='terrain'|'placement';

function Surface({data,exaggeration}:{data:TerrainData;exaggeration:number}){
  const geometry=useMemo(()=>{
    const {width,height,pixel_size_m,elevations,roi_mask}=data;
    const extent=Math.max(width,height)*pixel_size_m;
    const scale=100/extent;
    const finite=elevations.filter((v):v is number=>v!==null&&Number.isFinite(v));
    const datum=finite.reduce((a,b)=>a+b,0)/Math.max(finite.length,1);
    const low=Math.min(...finite),high=Math.max(...finite);
    const vertices=new Float32Array(width*height*3), colors=new Float32Array(width*height*3);
    const indices:number[]=[];
    const shade=new THREE.Color();
    const valid=(i:number)=>elevations[i]!==null&&Number.isFinite(elevations[i])&&roi_mask[i];
    for(let row=0;row<height;row++)for(let col=0;col<width;col++){
      const i=row*width+col, value=elevations[i]??datum;
      vertices.set([(col-(width-1)/2)*pixel_size_m*scale,(value-datum)*scale*exaggeration,(row-(height-1)/2)*pixel_size_m*scale],i*3);
      const t=(value-low)/Math.max(high-low,1);
      if((data.body as string)==='moon')shade.setHSL(0,0,.25+.29*t);
      else shade.setHSL(data.body==='mars'?.055+.025*t:.105+.06*t,.28,data.body==='mars'?.25+.28*t:.24+.29*t);
      colors.set([shade.r,shade.g,shade.b],i*3);
      if(row<height-1&&col<width-1){const a=i,b=i+1,c=i+width,d=c+1;if(valid(a)&&valid(c)&&valid(b))indices.push(a,c,b);if(valid(b)&&valid(c)&&valid(d))indices.push(b,c,d);}
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(vertices,3));geo.setAttribute('color',new THREE.BufferAttribute(colors,3));geo.setIndex(indices);geo.computeVertexNormals();return geo;
  },[data,exaggeration]);
  useEffect(()=>()=>geometry.dispose(),[geometry]);
  return <mesh geometry={geometry}><meshStandardMaterial vertexColors roughness={1} metalness={0} side={THREE.DoubleSide}/></mesh>;
}

export default function MeasuredTerrain({url,title,initialMode='terrain'}:{url:string;title?:string;initialMode?:TerrainMode}){
  const c=useUiCopy(); const {t,locale}=useI18n();
  const [data,setData]=useState<TerrainData|null>(null),[error,setError]=useState(''),[exaggeration,setExaggeration]=useState(1);
  const [mode,setMode]=useState<TerrainMode>(initialMode);
  useEffect(()=>{const controller=new AbortController();setData(null);setError('');setMode(initialMode);fetch(url,{signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(c("Relyef ma’lumotini olishda xato."));return r.json()}).then(v=>{if(!v.measured_dem||!Number.isInteger(v.width)||!Number.isInteger(v.height)||v.width<2||v.height<2||!Number.isFinite(v.pixel_size_m)||v.pixel_size_m<=0||v.elevations?.length!==v.width*v.height||v.roi_mask?.length!==v.width*v.height)throw new Error(c("Yaroqli haqiqiy DEM topilmadi."));setData(v)}).catch(e=>{if(e.name!=='AbortError')setError(e.message)});return()=>controller.abort()},[url,initialMode]);
  if(error)return <div className="terrain-loading error-message">{c(error)}</div>;
  if(!data)return <div className="terrain-loading"><span className="science-spinner"/>{c("Haqiqiy balandlik modeli yuklanmoqda…")}</div>;
  return <div className="terrain-workbench"><div className="terrain-mode-switch" role="group" aria-label={c("3D ko‘rinish turi")}><button aria-pressed={mode==='terrain'} onClick={()=>setMode('terrain')}><Layers size={14}/>{c("O‘lchangan relyef")}</button><button aria-pressed={mode==='placement'} onClick={()=>setMode('placement')}><Rocket size={14}/>{c("Apparat joylashtirish")}</button><span>{t({ru:`Сетка ${Math.round(data.pixel_size_m)} м · измеренная DEM`,en:`${Math.round(data.pixel_size_m)} m grid · measured DEM`,uz:`${Math.round(data.pixel_size_m)} m / katak · haqiqiy DEM`})}</span></div>{mode==='placement'?<Suspense fallback={<div className="terrain-loading"><span className="science-spinner"/>{c("Qo‘nish sahnasi yuklanmoqda…")}</div>}><MissionPlacement key={url} data={data} title={title}/></Suspense>:<div className="measured-terrain"><Canvas frameloop="demand" dpr={1} camera={{position:[75,65,90],fov:43,near:.1,far:1000}} gl={{antialias:false,powerPreference:'default'}}><color attach="background" args={['#131918']}/><hemisphereLight args={['#f1ecdb','#353c3b',2.3]}/><directionalLight position={[-60,85,30]} intensity={3} color="#fff0d4"/><Surface data={data} exaggeration={exaggeration}/><OrbitControls makeDefault enableDamping minDistance={20} maxDistance={240} maxPolarAngle={Math.PI*.48}/><gridHelper args={[130,13,'#46534b','#242f29']} position={[0,-5,0]}/></Canvas><div className="terrain-scale"><span>{t({ru:`Сетка ${data.pixel_size_m} м`,en:`${data.pixel_size_m} m grid`,uz:`${data.pixel_size_m} m / katak`})} · {Math.round(data.min_elevation_m).toLocaleString(locale)}…{Math.round(data.max_elevation_m).toLocaleString(locale)} m</span><label>{c("Balandlik masshtabi")}<select value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}><option value={1}>{c("1× — haqiqiy nisbat")}</option><option value={5}>{c("5× — bo‘rttirilgan")}</option><option value={10}>{c("10× — bo‘rttirilgan")}</option></select></label></div><div className="terrain-guidance">{c("Aylantirish: sichqoncha · Yaqinlashtirish: scroll · Relyef: haqiqiy DEM, ranglar: balandlik")}</div></div>}</div>;
}
