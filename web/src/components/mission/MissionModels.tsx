import {useEffect,useLayoutEffect,useMemo,useRef,type ReactNode} from 'react';
import * as THREE from 'three';
import {useFrame,useLoader,useThree} from '@react-three/fiber';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import type {TerrainData} from '../../science-types';
import {sampleTerrain,type MissionPoint} from './terrainMath';
import RocketModel,{ROCKET_FOOT_CENTERS,type RocketContact} from './RocketModel';

export type ApparatusKind='rocket'|'lander'|'station';
export const APPARATUS_SPECS={
  rocket:{height:18,footprintRadius:4.4,focusHeight:8.5,canFly:true},
  lander:{height:1.5,footprintRadius:3.2,focusHeight:1,canFly:true},
  station:{height:2.3,footprintRadius:1.15,focusHeight:1.1,canFly:false},
} as const;

/** Finite support-pose blend keeps takeoff/landing from snapping on sloped DEM. */
function SupportPose({height,rotation,motionPaused,children}:{height:number;rotation:THREE.Quaternion;motionPaused:boolean;children:ReactNode}){
  const group=useRef<THREE.Group>(null),{invalidate}=useThree();
  const initial=useRef({height,rotation:rotation.clone()});
  const transition=useRef({fromHeight:height,fromRotation:rotation.clone(),elapsed:.75});
  const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  useLayoutEffect(()=>{
    if(!group.current)return;
    clearTimeout(timer.current);timer.current=undefined;
    if(group.current.quaternion.angleTo(rotation)<1e-6&&Math.abs(group.current.position.y-height)<1e-6){transition.current.elapsed=.75;return;}
    transition.current.fromHeight=group.current.position.y;
    transition.current.fromRotation.copy(group.current.quaternion);
    transition.current.elapsed=matchMedia('(prefers-reduced-motion: reduce)').matches ? .75 : 0;
    if(!motionPaused&&!document.hidden)invalidate();
  },[height,rotation,invalidate]);
  useEffect(()=>{
    const resume=()=>{clearTimeout(timer.current);timer.current=undefined;if(!motionPaused&&!document.hidden&&transition.current.elapsed<.75)invalidate();};
    document.addEventListener('visibilitychange',resume);resume();
    return()=>{document.removeEventListener('visibilitychange',resume);clearTimeout(timer.current);timer.current=undefined;};
  },[motionPaused,invalidate]);
  useFrame((_,dt)=>{
    if(!group.current||motionPaused||document.hidden)return;
    const state=transition.current;
    if(state.elapsed>=.75){group.current.position.y=height;group.current.quaternion.copy(rotation);return;}
    state.elapsed=Math.min(.75,state.elapsed+Math.min(dt,.1));
    const t=state.elapsed/.75,ease=t*t*(3-2*t);
    group.current.position.y=THREE.MathUtils.lerp(state.fromHeight,height,ease);
    group.current.quaternion.slerpQuaternions(state.fromRotation,rotation,ease);
    if(state.elapsed<.75&&!timer.current)timer.current=setTimeout(()=>{timer.current=undefined;invalidate();},1000/30);
  });
  return <group ref={group} position={[0,initial.current.height,0]} quaternion={initial.current.rotation}>{children}</group>;
}

function solarTexture(){
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;const ctx=canvas.getContext('2d')!;
  ctx.fillStyle='#75828a';ctx.fillRect(0,0,512,512);
  for(let row=0;row<8;row++)for(let col=0;col<8;col++){const x=col*64+3,y=row*64+3;const g=ctx.createLinearGradient(x,y,x+60,y+60);g.addColorStop(0,'#112030');g.addColorStop(1,'#233b50');ctx.fillStyle=g;ctx.fillRect(x,y,58,58);ctx.fillStyle='#9aafb9';ctx.fillRect(x+18,y,1,58);ctx.fillRect(x+39,y,1,58);ctx.strokeStyle='#6a839d66';for(let k=5;k<58;k+=5){ctx.beginPath();ctx.moveTo(x,y+k);ctx.lineTo(x+58,y+k);ctx.stroke();}}
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return texture;
}
function Strut({a,b,radius=.06,color='#aab3b7'}:{a:[number,number,number];b:[number,number,number];radius?:number;color?:string}){
  const transform=useMemo(()=>{const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b),direction=end.clone().sub(start);return {position:start.add(end).multiplyScalar(.5),length:direction.length(),rotation:new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize())};},[...a,...b]);
  return <mesh position={transform.position} quaternion={transform.rotation} castShadow><cylinderGeometry args={[radius,radius,transform.length,10]}/><meshStandardMaterial color={color} roughness={.28} metalness={.8}/></mesh>;
}
const INSIGHT_SCALE=6/6.1418155;
const INSIGHT_MIN_Y=-.635891;
const CONTACTS=[new THREE.Vector3(.00110161,0,-1.27359359),new THREE.Vector3(-1.10351501,0,.63584522),new THREE.Vector3(1.10241332,0,.63774987)].map(v=>v.multiplyScalar(INSIGHT_SCALE));

/** Rigid three-foot support fit: source model geometry stays intact and at true metre scale. */
function Lander({data,point,grounded=true,motionPaused=false}:{data:TerrainData;point:MissionPoint;grounded?:boolean;motionPaused?:boolean}){
  const source=useLoader(GLTFLoader,'/models/mission/lander.glb');
  const object=useMemo(()=>{const clone=source.scene.clone(true);clone.traverse(node=>{if(node instanceof THREE.Mesh){node.castShadow=true;node.receiveShadow=true;}});return clone;},[source]);
  const support=useMemo(()=>{
    if(!grounded)return {rotation:new THREE.Quaternion(),height:0};
    const rotation=new THREE.Quaternion(),up=new THREE.Vector3(0,1,0);
    let height=0;
    for(let iteration=0;iteration<7;iteration++){
      const feet=CONTACTS.map(v=>v.clone().applyQuaternion(rotation));
      const samples=feet.map(v=>sampleTerrain(data,point.x+v.x,point.z+v.z));
      if(samples.some(v=>!v))return {rotation:new THREE.Quaternion(),height:0};
      const ground=feet.map((v,i)=>new THREE.Vector3(v.x,samples[i]!.y,v.z));
      const normal=ground[1].clone().sub(ground[0]).cross(ground[2].clone().sub(ground[0])).normalize();
      if(normal.y<0)normal.negate();
      rotation.setFromUnitVectors(up,normal);
    }
    const feet=CONTACTS.map(v=>v.clone().applyQuaternion(rotation));
    height=Math.max(...feet.map(v=>(sampleTerrain(data,point.x+v.x,point.z+v.z)?.y??point.y)-point.y-v.y));
    return {rotation,height};
  },[data,point,grounded]);
  return <SupportPose height={support.height} rotation={support.rotation} motionPaused={motionPaused}><group scale={INSIGHT_SCALE} position={[0,-INSIGHT_MIN_Y*INSIGHT_SCALE,0]}><primitive object={object}/></group></SupportPose>;
}

function ExpeditionRocket({data,point,grounded,motionPaused}:{data:TerrainData;point:MissionPoint;grounded:boolean;motionPaused:boolean}){
  const support=useMemo(()=>{
    const rotation=new THREE.Quaternion(),up=new THREE.Vector3(0,1,0);
    const flat:RocketContact[]=ROCKET_FOOT_CENTERS.map(()=>({height:0,normal:[0,1,0]}));
    if(!grounded)return {rotation,height:0,contacts:flat};
    // Fit all four support locations, then let the telescopic struts meet the
    // actual rendered DEM triangle beneath each foot, including triangle edges.
    for(let iteration=0;iteration<5;iteration++){
      const feet=ROCKET_FOOT_CENTERS.map(p=>p.clone().applyQuaternion(rotation));
      const samples=feet.map(p=>sampleTerrain(data,point.x+p.x,point.z+p.z));
      if(samples.some(sample=>!sample))return null;
      const mean=feet.reduce((sum,p,i)=>sum.add(new THREE.Vector3(p.x,samples[i]!.y,p.z)),new THREE.Vector3()).multiplyScalar(.25);
      let xx=0,xz=0,zz=0,xy=0,zy=0;
      feet.forEach((p,i)=>{const x=p.x-mean.x,z=p.z-mean.z,y=samples[i]!.y-mean.y;xx+=x*x;xz+=x*z;zz+=z*z;xy+=x*y;zy+=z*y;});
      const determinant=xx*zz-xz*xz;
      if(Math.abs(determinant)<1e-8)return null;
      const dx=(xy*zz-zy*xz)/determinant,dz=(zy*xx-xy*xz)/determinant;
      rotation.setFromUnitVectors(up,new THREE.Vector3(-dx,1,-dz).normalize());
    }
    const rotatedFeet=ROCKET_FOOT_CENTERS.map(p=>p.clone().applyQuaternion(rotation));
    const height=Math.max(...rotatedFeet.map(p=>(sampleTerrain(data,point.x+p.x,point.z+p.z)?.y??point.y)-point.y-p.y));
    const rotatedUp=up.clone().applyQuaternion(rotation),inverse=rotation.clone().invert();
    const contacts:RocketContact[]=rotatedFeet.map(foot=>{
      let adjustment=0;
      let sample=sampleTerrain(data,point.x+foot.x,point.z+foot.z)!;
      for(let iteration=0;iteration<5;iteration++){
        const current=sampleTerrain(data,point.x+foot.x+rotatedUp.x*adjustment,point.z+foot.z+rotatedUp.z*adjustment);
        if(current)sample=current;
        adjustment=(sample.y-point.y-height-foot.y)/Math.max(rotatedUp.y,.1);
      }
      const normal=new THREE.Vector3(...sample.normal).applyQuaternion(inverse).normalize();
      return {height:adjustment,normal:normal.toArray() as [number,number,number]};
    });
    return {rotation,height,contacts};
  },[data,point,grounded]);
  if(!support)return null;
  return <SupportPose height={support.height} rotation={support.rotation} motionPaused={motionPaused}><RocketModel contacts={support.contacts}/></SupportPose>;
}

function ScienceStation({feet}:{feet:[number,number,number][]}){
  const solar=useMemo(solarTexture,[]);useEffect(()=>()=>solar.dispose(),[solar]);
  const base=Math.max(0,...feet.map(foot=>foot[1]));
  return <group><mesh position={[0,base+.72,0]} castShadow><boxGeometry args={[1.12,.8,.85]}/><meshStandardMaterial color="#d1d7d4" roughness={.33} metalness={.65}/></mesh><mesh position={[0,base+1.15,0]} castShadow><boxGeometry args={[1.22,.09,.95]}/><meshStandardMaterial color="#323c44" roughness={.38} metalness={.8}/></mesh><Strut a={[0,base+1.15,0]} b={[0,base+2.2,0]} radius={.035}/><mesh position={[0,base+2.15,0]} castShadow><boxGeometry args={[.4,.22,.23]}/><meshStandardMaterial color="#b8c7ca" roughness={.25} metalness={.75}/></mesh><mesh position={[0,base+2.15,.13]} rotation={[Math.PI/2,0,0]}><cylinderGeometry args={[.075,.075,.02,20]}/><meshPhysicalMaterial color="#0b1620" roughness={.08} metalness={.5} clearcoat={1}/></mesh><group position={[1.3,base+1.15,0]} rotation={[0,0,-.2]}><mesh castShadow><boxGeometry args={[1.5,.06,1.2]}/><meshStandardMaterial color="#8e9ca3" metalness={.7} roughness={.3}/></mesh><mesh position={[0,.035,0]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[1.44,1.14]}/><meshStandardMaterial map={solar} metalness={.45} roughness={.25}/></mesh></group>{feet.map((foot,i)=><group key={i}><Strut a={[Math.sign(foot[0])*.4,base+.55,Math.sign(foot[2])*.3]} b={[foot[0],foot[1]+.06,foot[2]]} radius={.028}/><mesh position={[foot[0],foot[1]+.04,foot[2]]}><cylinderGeometry args={[.16,.2,.08,16]}/><meshStandardMaterial color="#a3aaab" metalness={.6} roughness={.45}/></mesh></group>)}</group>;
}
export default function MissionModels({kind,feet,data,point,grounded=true,motionPaused=false}:{kind:ApparatusKind;feet:[number,number,number][];data:TerrainData;point:MissionPoint;grounded?:boolean;motionPaused?:boolean}){return kind==='rocket'?<ExpeditionRocket data={data} point={point} grounded={grounded} motionPaused={motionPaused}/>:kind==='lander'?<Lander data={data} point={point} grounded={grounded} motionPaused={motionPaused}/>:<ScienceStation feet={feet}/>;}
