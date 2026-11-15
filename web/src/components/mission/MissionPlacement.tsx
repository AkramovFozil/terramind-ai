import {useUiCopy} from '../../ui-copy';
import {useI18n} from '../../i18n';
import {Component,Suspense,useCallback,useEffect,useMemo,useRef,useState,type ReactNode,type MutableRefObject} from 'react';
import {Canvas,useFrame,useLoader,useThree,type ThreeEvent} from '@react-three/fiber';
import {Html} from '@react-three/drei';
import {ArrowDownToLine,Box,Focus,MapPin,Maximize2,Minimize2,Pause,Play,Rocket,Map} from 'lucide-react';
import * as THREE from 'three';
import type {TerrainData} from '../../science-types';
import {APPARATUS_SPECS,type ApparatusKind} from './MissionModels';
import {MissionFlight,MissionCameraRig,createFlightPose,type FlightPose,type MissionAction as Action,type MissionView as View} from './MissionFlight';
import {initialMissionPoint,missionPoint,validTerrain,type MissionPoint} from './terrainMath';
import './mission.css';

type Quality='medium'|'high';

function TerrainSurface({data,onPick,picking}:{data:TerrainData;onPick:(x:number,z:number)=>void;picking:boolean}){
  const sources=useLoader(THREE.TextureLoader,['/textures/terrain/sand-color.jpg','/textures/terrain/sand-normal.jpg']);
  const [texture,normal]=useMemo(()=>sources.map((source,i)=>{const map=source.clone();map.wrapS=map.wrapT=THREE.RepeatWrapping;map.colorSpace=i===0?THREE.SRGBColorSpace:THREE.NoColorSpace;map.anisotropy=2;map.needsUpdate=true;return map;}),[sources]);
  const geometry=useMemo(()=>{
    const {width,height,pixel_size_m,elevations,roi_mask,median_elevation_m}=data;
    const vertices=new Float32Array(width*height*3),uv=new Float32Array(width*height*2),indices:number[]=[];
    const valid=(i:number)=>roi_mask[i]&&elevations[i]!==null&&Number.isFinite(elevations[i]);
    for(let row=0;row<height;row++)for(let col=0;col<width;col++){
      const i=row*width+col,x=(col-(width-1)/2)*pixel_size_m,z=(row-(height-1)/2)*pixel_size_m;
      vertices.set([x,(elevations[i]??median_elevation_m)-median_elevation_m,z],i*3);uv.set([x/9,z/9],i*2);
      if(row<height-1&&col<width-1){const a=i,b=i+1,c=i+width,d=c+1;if(valid(a)&&valid(c)&&valid(b))indices.push(a,c,b);if(valid(b)&&valid(c)&&valid(d))indices.push(b,c,d);}
    }
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(vertices,3));geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));geometry.setIndex(indices);geometry.computeVertexNormals();return geometry;
  },[data]);
  useEffect(()=>()=>{geometry.dispose();texture.dispose();normal.dispose();},[geometry,texture,normal]);
  const body=String(data.body),color=body==='mars'?'#a37959':body==='moon'?'#858783':'#858375';
  const pick=(e:ThreeEvent<MouseEvent>)=>{if(picking&&e.delta<5){e.stopPropagation();onPick(e.point.x,e.point.z);}};
  return <mesh geometry={geometry} onClick={pick} receiveShadow><meshStandardMaterial color={color} map={texture} normalMap={normal} normalScale={new THREE.Vector2(.3,.3)} roughness={.96} metalness={0} side={THREE.DoubleSide}/></mesh>;
}

function MissionEnvironment(){
  const {gl,scene,invalidate}=useThree();
  useEffect(()=>{
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=256;const ctx=canvas.getContext('2d')!;
    ctx.fillStyle='#57616a';ctx.fillRect(0,0,512,256);
    const gradient=ctx.createRadialGradient(125,64,4,125,64,95);gradient.addColorStop(0,'#fff5dc');gradient.addColorStop(.3,'#c5c1b8');gradient.addColorStop(1,'#57616a');ctx.fillStyle=gradient;ctx.fillRect(0,0,260,180);
    ctx.fillStyle='#a4b1b9';ctx.fillRect(330,55,70,110);ctx.fillStyle='#72665a';ctx.fillRect(0,160,512,96);
    const input=new THREE.CanvasTexture(canvas);input.colorSpace=THREE.SRGBColorSpace;input.mapping=THREE.EquirectangularReflectionMapping;
    const generator=new THREE.PMREMGenerator(gl),result=generator.fromEquirectangular(input),previous=scene.environment;
    scene.environment=result.texture;scene.environmentIntensity=.9;generator.dispose();input.dispose();invalidate();
    return()=>{scene.environment=previous;result.dispose();};
  },[gl,scene,invalidate]);return null;
}

function FramePump({active,command,paused}:{active:boolean;command:number;paused:boolean}){
  const {invalidate}=useThree();
  useEffect(()=>{
    let timer:ReturnType<typeof setTimeout>|undefined,cancelled=false;
    const frame=()=>{timer=undefined;if(cancelled||document.hidden||paused||!active)return;invalidate();timer=setTimeout(frame,1000/30);};
    const visibility=()=>{clearTimeout(timer);timer=undefined;if(!document.hidden){invalidate();frame();}};
    document.addEventListener('visibilitychange',visibility);invalidate();frame();
    return()=>{cancelled=true;clearTimeout(timer);document.removeEventListener('visibilitychange',visibility);};
  },[active,command,paused,invalidate]);return null;
}

function MissionSun({point,poseRef,quality}:{point:MissionPoint|null;poseRef:MutableRefObject<FlightPose>;quality:Quality}){
  const light=useRef<THREE.DirectionalLight>(null),target=useMemo(()=>new THREE.Object3D(),[]);
  useFrame(()=>{const p=poseRef.current;if(!light.current)return;const x=p.initialized?p.position.x:point?.x??0,y=p.initialized?p.position.y:point?.y??0,z=p.initialized?p.position.z:point?.z??0;target.position.set(x,y+6,z);target.updateMatrixWorld();light.current.position.set(x-140,y+200,z+100);});
  return <><primitive object={target}/><directionalLight ref={light} position={[(point?.x??0)-140,(point?.y??0)+200,(point?.z??0)+100]} target={target} intensity={3.8} color="#fff1d5" castShadow shadow-mapSize={quality==='high'?[2048,2048]:[1024,1024]} shadow-camera-near={1} shadow-camera-far={500} shadow-camera-left={-30} shadow-camera-right={30} shadow-camera-top={30} shadow-camera-bottom={-30} shadow-bias={-.00015} shadow-normalBias={.04}/></>;
}

function MissionCanvas({data,point,kind,action,run,view,command,paused,reduced,quality,picking,onPick,onActionComplete,onBlocked}:{data:TerrainData;point:MissionPoint|null;kind:ApparatusKind;action:Action;run:number;view:View;command:number;paused:boolean;reduced:boolean;quality:Quality;picking:boolean;onPick:(x:number,z:number)=>void;onActionComplete:(action:'placed'|'flying')=>void;onBlocked:(message:string)=>void}){
  const c=useUiCopy();
  const extent=Math.max(data.width,data.height)*data.pixel_size_m;
  const poseRef=useRef(createFlightPose());
  const initialCamera=useMemo(()=>({position:[(point?.x??0)+26,(point?.y??0)+17,(point?.z??0)+34] as [number,number,number],fov:43,near:.1,far:extent*8}),[data]);
  return <Canvas frameloop="demand" dpr={quality==='high'?[1,1.5]:1} shadows camera={initialCamera} gl={{antialias:true,powerPreference:'default'}} onCreated={({gl})=>{gl.toneMapping=THREE.ACESFilmicToneMapping;gl.toneMappingExposure=1.15;}}>
    <color attach="background" args={[String(data.body)==='mars'?'#28211c':'#13171b']}/>{data.body!=='moon'&&<fogExp2 attach="fog" args={[data.body==='mars'?'#66503f':'#5b6163',.000045]}/>}<MissionEnvironment/>
    <ambientLight intensity={.3}/><hemisphereLight args={['#dae1e6','#625a49',.75]}/>
    <MissionSun point={point} poseRef={poseRef} quality={quality}/>
    <directionalLight position={[200,150,-100]} intensity={.22} color="#a9cce6"/>
    <TerrainSurface data={data} onPick={onPick} picking={picking}/>
    {point&&action!=='empty'&&<Suspense fallback={<Html position={[point.x,point.y+2,point.z]} center><span className="mission-model-loading">{c('Raketa modeli yuklanmoqda…')}</span></Html>}><MissionFlight data={data} point={point} kind={kind} action={action} run={run} paused={paused} reduced={reduced} poseRef={poseRef} onActionComplete={onActionComplete} onBlocked={onBlocked}/></Suspense>}
    {point&&view==='overview'&&<Html position={[point.x,point.y+extent*.004,point.z]} center style={{pointerEvents:'none'}}><span className="mission-map-pin"><MapPin size={20}/><span>{c('Tanlangan nuqta')}</span></span></Html>}
    <MissionCameraRig data={data} point={point} kind={kind} view={view} command={command} run={run} action={action} poseRef={poseRef} paused={paused} reduced={reduced}/>
    <FramePump active={!reduced&&(action==='landing'||action==='launching'||action==='flying')} command={command+run} paused={paused}/>
  </Canvas>;
}

class MissionBoundary extends Component<{children:ReactNode;message:string},{error:boolean}>{state={error:false};static getDerivedStateFromError(){return {error:true};}render(){return this.state.error?<div className="mission-error">{this.props.message}</div>:this.props.children;}}

export default function MissionPlacement({data,title}:{data:TerrainData;title?:string}){
  const c=useUiCopy(); const {t,locale}=useI18n();
  const [kind,setKind]=useState<ApparatusKind>('rocket'),[point,setPoint]=useState<MissionPoint|null>(()=>initialMissionPoint(data,4.4));
  const [action,setAction]=useState<Action>('placed'),[view,setView]=useState<View>('close'),[picking,setPicking]=useState(false),[quality,setQuality]=useState<Quality>('medium');
  const [run,setRun]=useState(0),[command,setCommand]=useState(0),[paused,setPaused]=useState(false),[error,setError]=useState(''),[hidden,setHidden]=useState(document.hidden);
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  const root=useRef<HTMLDivElement>(null),fullscreenButton=useRef<HTMLButtonElement>(null);const [visible,setVisible]=useState(true),[expanded,setExpanded]=useState(false);
  const moving=action==='landing'||action==='launching'||action==='flying';
  useEffect(()=>{setKind('rocket');setPoint(initialMissionPoint(data,4.4));setAction('placed');setView('close');setPicking(false);setPaused(false);setError('');setCommand(c=>c+1);},[data]);
  useEffect(()=>{const change=()=>setHidden(document.hidden),media=matchMedia('(prefers-reduced-motion: reduce)'),motion=()=>setReduced(media.matches);document.addEventListener('visibilitychange',change);media.addEventListener('change',motion);return()=>{document.removeEventListener('visibilitychange',change);media.removeEventListener('change',motion);};},[]);
  useEffect(()=>{if(!root.current)return;const observer=new IntersectionObserver(([entry])=>setVisible(entry.isIntersecting),{threshold:.02});observer.observe(root.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{const change=()=>{setExpanded(document.fullscreenElement===root.current);setCommand(c=>c+1);};document.addEventListener('fullscreenchange',change);return()=>document.removeEventListener('fullscreenchange',change);},[]);
  useEffect(()=>{if(!expanded)return;const prior=document.body.style.overflow;document.body.style.overflow='hidden';const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.stopImmediatePropagation();if(document.fullscreenElement===root.current)void document.exitFullscreen();else setExpanded(false);fullscreenButton.current?.focus();}};window.addEventListener('keydown',escape,true);return()=>{document.body.style.overflow=prior;window.removeEventListener('keydown',escape,true);};},[expanded]);
  const toggleFullscreen=async()=>{if(expanded){if(document.fullscreenElement===root.current)await document.exitFullscreen();else setExpanded(false);}else{setExpanded(true);try{await root.current?.requestFullscreen?.();}catch{/* The same expanded scene remains available when browser fullscreen is restricted. */}}setCommand(c=>c+1);};
  const pick=useCallback((x:number,z:number)=>{const found=missionPoint(data,x,z,APPARATUS_SPECS[kind].footprintRadius);if(!found){setError(c("Bu nuqta yoki apparat oyoqlari ostida DEM ma’lumoti yo‘q. Boshqa joyni tanlang."));return;}setPoint(found);setAction('placed');setView('close');setRun(r=>r+1);setCommand(c=>c+1);setPaused(false);setError('');setPicking(false);},[data,kind]);
  const start=(next:Action)=>{if(!point)return;setAction(next);setError('');setPicking(false);setPaused(false);setView('close');setRun(r=>r+1);setCommand(c=>c+1);};
  const completed=useCallback((next:'placed'|'flying')=>setAction(next),[]);
  const blocked=useCallback((message:string)=>{setPaused(true);setError(message);},[]);
  const changeKind=(next:ApparatusKind)=>{setError('');setKind(next);setAction('placed');setPaused(false);setView('close');setPicking(false);setRun(r=>r+1);setCommand(c=>c+1);setPoint(point?missionPoint(data,point.x,point.z,APPARATUS_SPECS[next].footprintRadius):initialMissionPoint(data,APPARATUS_SPECS[next].footprintRadius));};
  const overview=()=>{setAction('empty');setError('');setPaused(false);setView('overview');setPicking(true);setCommand(c=>c+1);};
  if(!validTerrain(data))return <div className="mission-error">{c("Joylashtirish uchun haqiqiy, yaroqli DEM kerak.")}</div>;
  return <div className={`mission-placement ${expanded?'is-expanded':''}`} ref={root}>
    <div className="mission-toolbar"><label>{c("Apparat")}<select aria-label={c("Joylashtiriladigan apparat")} value={kind} onChange={e=>changeKind(e.target.value as ApparatusKind)}><option value="rocket">{c("TerraMind raketasi · 18 m")}</option><option value="lander">{c("InSight · qanot kengligi 6 m")}</option><option value="station">{c("Ilmiy stansiya · 2 m")}</option></select></label><button onClick={overview} aria-pressed={picking}><MapPin size={14}/>{c("Joy tanlash")}</button>{APPARATUS_SPECS[kind].canFly?<><button className="mission-land-button" disabled={!point} onClick={()=>start('landing')}><ArrowDownToLine size={15}/>{action==='flying'||action==='launching'?c("Tanlangan joyga qo‘nish"):c("Qo‘nishni ko‘rsatish")}</button>{kind==='rocket'&&<button disabled={!point||action==='launching'||action==='flying'} onClick={()=>start('launching')}><Rocket size={15}/>{c("Uchirish va aylanish")}</button>}</>:<button disabled={!point} onClick={()=>start('placed')}><Box size={14}/>{c("Joylashtirish")}</button>}<button className="mission-fullscreen-button" ref={fullscreenButton} onClick={()=>void toggleFullscreen()} aria-pressed={expanded}>{expanded?<Minimize2 size={15}/>:<Maximize2 size={15}/>}<span>{expanded?c("Kichraytirish"):c("Katta ekranda ochish")}</span></button><label className="mission-quality"><span>{c("Grafika")}</span><select aria-label={c("Missiya grafikasi")} value={quality} onChange={e=>setQuality(e.target.value as Quality)}><option value="medium">{c("O‘rta")}</option><option value="high">{c("Yuqori")}</option></select></label></div>
    <div className={`mission-canvas ${picking?'is-picking':''}`}>
      <MissionBoundary message={c('3D ko‘rinish yuklanmadi. Sahifani yangilab qayta urinib ko‘ring.')}><MissionCanvas data={data} point={point} kind={kind} action={action} run={run} view={view} command={command} paused={paused||hidden||!visible} reduced={reduced} quality={quality} picking={picking} onPick={pick} onActionComplete={completed} onBlocked={blocked}/></MissionBoundary>
      <div className="mission-watermark">AI-generated</div>
      <div className="mission-scene-caption"><span>{title??`${data.body==='earth'?c("Yer"):String(data.body)==='moon'?c("Oy"):c("Mars")} · ${t({ru:'выбранный участок',en:'selected region',uz:'tanlangan hudud'})}`}</span><strong>{view==='overview'?c("HUDUD KO‘RINISHI"):action==='landing'?c("QO‘NISH"):action==='launching'?c("UCHIRISH"):action==='flying'?(reduced?c("PARVOZ HOLATI"):c("HUDUD BO‘YLAB PARVOZ")):action==='placed'?c("YIRIK PLAN"):c("NUQTA TANLANDI")}{paused?c(" · PAUZA"):''}</strong></div>
      <div className="mission-view-controls"><button onClick={()=>{setView('overview');setPicking(false);setCommand(c=>c+1);}} title={c("Butun hudud")} aria-label={c("Butun hududni ko‘rsatish")}><Map size={16}/></button><button disabled={!point} onClick={()=>{if(action==='empty')setAction('placed');setView('close');setPicking(false);setCommand(c=>c+1);}} title={c("Yirik plan")} aria-label={c("Raketaga yaqinlashish")}><Focus size={16}/></button>{moving&&<button onClick={()=>setPaused(p=>!p)} aria-label={paused?c("Parvozni davom ettirish"):c("Parvozni to‘xtatish")}>{paused?<Play size={16}/>:<Pause size={16}/>}</button>}</div>
      {picking&&<div className="mission-pick-hint">{c("Relyef ustiga bosing — apparat qo‘yiladigan nuqtani tanlang")}</div>}
      {!picking&&<div className="mission-camera-hint">{c('Aylantirish: sudrang · Yaqinlashish: scroll')}{reduced?c(" · Kamaytirilgan animatsiya"):''}</div>}
      {!point&&<div className="mission-no-point">{c("Bu hududda apparat izini joylashtirish uchun yetarli yaroqli DEM yo‘q.")}</div>}
    </div>
    <div className="mission-readout" role="status">{point?<><span>{t({ru:'От центра',en:'From centre',uz:'Markazdan'})}: E {point.x.toLocaleString(locale,{maximumFractionDigits:1})} m · S {point.z.toLocaleString(locale,{maximumFractionDigits:1})} m</span><span>{c('Balandlik')}: {point.elevation.toLocaleString(locale,{maximumFractionDigits:1})} m</span><span>{t({ru:'Уклон DEM',en:'DEM slope',uz:'DEM qiyaligi'})}: {point.slopeDeg.toLocaleString(locale,{maximumFractionDigits:1})}°</span></>:<span>{c("Nuqta tanlanmagan")}</span>}<span>{t({ru:`Масштаб 1× · сетка ${data.pixel_size_m.toFixed(0)} м`,en:`1× scale · ${data.pixel_size_m.toFixed(0)} m grid`,uz:`1× masshtab · ${data.pixel_size_m.toFixed(0)} m / katak`})}</span></div>
    {error&&<div className="mission-inline-error" role="alert">{c(error)}</div>}
    <p className="mission-disclosure">{t({ru:`Измеренная DEM · AI-generated ${kind==='rocket'?'концепт ракеты, ':''}сцена и анимация. Полёт — визуальная симуляция, а не оценка безопасности посадки. Детали меньше ячейки DEM не измерены.`,en:`Measured DEM · AI-generated ${kind==='rocket'?'rocket concept, ':''}scene and animation. Flight is an illustrative simulation, not a landing-safety assessment. Sub-grid details are not measured.`,uz:`Haqiqiy DEM · AI-generated ${kind==='rocket'?'konsept raketa, ':''}sahna va animatsiya. Parvoz tasviriy simulyatsiya; qo‘nish xavfsizligi bahosi emas. DEM katagidan kichik detallar o‘lchanmagan.`})} {kind==='lander'&&<a href="/models/mission/SOURCE-CREDITS.txt" target="_blank" rel="noreferrer">InSight: NASA / Brian E. Kumanchik</a>}</p>
  </div>;
}
