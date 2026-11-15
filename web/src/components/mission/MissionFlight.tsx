import {useEffect,useMemo,useRef,useState,type MutableRefObject} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import {OrbitControls} from '@react-three/drei';
import * as THREE from 'three';
import type {TerrainData} from '../../science-types';
import MissionModels,{APPARATUS_SPECS,type ApparatusKind} from './MissionModels';
import {missionPoint,sampleTerrain,type MissionPoint} from './terrainMath';

export type MissionAction='empty'|'placed'|'landing'|'launching'|'flying';
export type MissionView='overview'|'close';
export type FlightPose={position:THREE.Vector3;quaternion:THREE.Quaternion;altitude:number;phaseProgress:number;height:number;moving:boolean;initialized:boolean;blocked:boolean;anchorKey:string;orbitPhase:number};
export function createFlightPose():FlightPose{return {position:new THREE.Vector3(),quaternion:new THREE.Quaternion(),altitude:0,phaseProgress:0,height:18,moving:false,initialized:false,blocked:false,anchorKey:'',orbitPhase:0};}

type FlightProps={data:TerrainData;point:MissionPoint;kind:ApparatusKind;action:MissionAction;run:number;paused:boolean;reduced:boolean;poseRef:MutableRefObject<FlightPose>;onActionComplete:(action:'placed'|'flying')=>void;onBlocked?:(message:string)=>void};
const LANDING_TIME=9.6,LAUNCH_TIME=7.2;
const smooth=(t:number)=>{const x=THREE.MathUtils.clamp(t,0,1);return x*x*(3-2*x);};
const orbitOffset=(phase:number,radius:number)=>new THREE.Vector3(Math.sin(phase)*radius,0,Math.sin(phase*2)*radius*.58);
const UP=new THREE.Vector3(0,1,0);

/** A small closed route wholly inside available DEM, not a claimed flight-safety assessment. */
function measuredRoute(data:TerrainData,point:MissionPoint,radius:number){
  for(const distance of [120,90,60,35,18,8,0]){
    let highest=point.y,valid=true;
    for(let i=0;i<=192;i++){
      const offset=orbitOffset(i/192*Math.PI*2,distance);
      const sample=missionPoint(data,point.x+offset.x,point.z+offset.z,radius);
      if(!sample){valid=false;break;}
      highest=Math.max(highest,sample.y);
    }
    if(valid)return {radius:distance,cruiseY:Math.max(point.y+75,highest+60)};
  }
  return {radius:0,cruiseY:point.y+75};
}

function dustSprite(){
  const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;const ctx=canvas.getContext('2d')!;
  const gradient=ctx.createRadialGradient(64,64,0,64,64,64);gradient.addColorStop(0,'rgba(255,255,255,.7)');gradient.addColorStop(.25,'rgba(255,255,255,.35)');gradient.addColorStop(.65,'rgba(255,255,255,.08)');gradient.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=gradient;ctx.fillRect(0,0,128,128);return new THREE.CanvasTexture(canvas);
}
function exhaustSprite(){
  const canvas=document.createElement('canvas');canvas.width=128;canvas.height=256;
  const ctx=canvas.getContext('2d')!,pixels=ctx.createImageData(canvas.width,canvas.height);
  for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
    const t=y/(canvas.height-1),radial=(x/(canvas.width-1)*2-1),width=.2+.5*Math.pow(Math.sin(t*Math.PI),.7);
    const axial=Math.pow(1-t,1.05)*Math.min(1,t/.025),edge=Math.exp(-3.5*Math.pow(radial/width,2));
    const shock=.88+.12*Math.cos(t*32),hot=Math.pow(1-t,2),index=(y*canvas.width+x)*4;
    pixels.data[index]=110+145*hot;pixels.data[index+1]=170+85*Math.pow(1-t,1.2);pixels.data[index+2]=255;pixels.data[index+3]=255*axial*edge*shock;
  }
  ctx.putImageData(pixels,0,0);const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return texture;
}

export function MissionFlight({data,point,kind,action,run,paused,reduced,poseRef,onActionComplete,onBlocked}:FlightProps){
  const spec=APPARATUS_SPECS[kind],{invalidate}=useThree();
  const craft=useRef<THREE.Group>(null),engine=useRef<THREE.Group>(null),engineLight=useRef<THREE.PointLight>(null),dust=useRef<THREE.Points>(null);
  const clock=useRef({key:'',elapsed:0,start:new THREE.Vector3(),rotation:new THREE.Quaternion(),orbit:0,reported:false,groundEntry:false,blocked:false});
  const callback=useRef(onActionComplete),blockedCallback=useRef(onBlocked);callback.current=onActionComplete;blockedCallback.current=onBlocked;
  const [grounded,setGrounded]=useState(action==='placed'),groundedRef=useRef(action==='placed');
  const anchorKey=`${data.body}:${data.center.lat}:${data.center.lon}:${point.x}:${point.z}:${kind}`;
  const controlKey=`${anchorKey}:${action}:${run}`;
  const route=useMemo(()=>measuredRoute(data,point,spec.footprintRadius),[data,point,spec.footprintRadius]);
  const dustMap=useMemo(dustSprite,[]),dustGeometry=useMemo(()=>{const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(48*3),3));return geometry;},[]);
  const exhaust=useMemo(()=>{
    const map=exhaustSprite();
    const material=()=>new THREE.MeshBasicMaterial({map,transparent:true,opacity:0,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide,toneMapped:false});
    return {map,outer:material(),core:material(),jets:material()};
  },[]);
  const desired=useMemo(()=>new THREE.Vector3(),[]),orientation=useMemo(()=>new THREE.Quaternion(),[]),aimed=useMemo(()=>new THREE.Quaternion(),[]),euler=useMemo(()=>new THREE.Euler(),[]);
  useEffect(()=>()=>{dustMap.dispose();dustGeometry.dispose();exhaust.map.dispose();exhaust.outer.dispose();exhaust.core.dispose();exhaust.jets.dispose();},[dustMap,dustGeometry,exhaust]);
  useEffect(()=>{
    const pose=poseRef.current,state=clock.current;
    const continued=pose.initialized&&pose.anchorKey===anchorKey&&pose.altitude>.4;
    if(pose.anchorKey!==anchorKey){pose.position.set(point.x,point.y,point.z);pose.quaternion.identity();pose.altitude=0;pose.orbitPhase=0;pose.initialized=false;}
    pose.anchorKey=anchorKey;pose.height=spec.height;pose.blocked=false;pose.moving=action==='landing'||action==='launching'||action==='flying';
    state.key=controlKey;state.elapsed=0;state.reported=false;state.blocked=false;state.orbit=continued?pose.orbitPhase:0;
    if(action==='placed'||action==='empty'||!spec.canFly){pose.position.set(point.x,point.y,point.z);pose.quaternion.identity();pose.altitude=0;pose.moving=false;}
    else if(action==='landing'&&!continued){pose.position.set(point.x,point.y+(kind==='rocket'?90:32),point.z);pose.quaternion.identity();pose.altitude=kind==='rocket'?90:32;}
    state.start.copy(pose.position);state.rotation.copy(pose.quaternion);state.groundEntry=action==='flying'&&pose.altitude<5;
    pose.initialized=true;invalidate();
  },[anchorKey,controlKey,action,kind,point,poseRef,spec.height,spec.canFly,invalidate]);

  useFrame((_,dt)=>{
    const state=clock.current,pose=poseRef.current;
    if(state.key!==controlKey||!craft.current)return;
    const frozen=paused||document.hidden;
    const block=(message:string)=>{if(!state.blocked){state.blocked=true;pose.blocked=true;pose.moving=false;blockedCallback.current?.(message);}};
    if(!frozen&&!state.blocked)state.elapsed+=Math.min(dt,.1);
    let progress=1,power=0,active=spec.canFly&&(action==='landing'||action==='launching'||action==='flying');
    desired.copy(pose.position);orientation.copy(pose.quaternion);
    if(action==='placed'||action==='empty'||!spec.canFly){desired.set(point.x,point.y,point.z);orientation.identity();active=false;}
    else if(action==='landing'){
      progress=reduced?1:Math.min(state.elapsed/LANDING_TIME,1);
      const movement=Math.min(progress*LANDING_TIME/(LANDING_TIME-1),1),lateral=smooth(movement/.68),correction=Math.sin(movement*Math.PI)*Math.pow(1-movement,2);
      desired.set(THREE.MathUtils.lerp(state.start.x,point.x,lateral)+Math.sin(movement*10)*correction*1.2,point.y+(state.start.y-point.y)*Math.pow(1-movement,2.35),THREE.MathUtils.lerp(state.start.z,point.z,lateral)+Math.sin(movement*7)*correction*.85);
      const ground=sampleTerrain(data,desired.x,desired.z);
      if(ground&&movement<.96)desired.y=Math.max(desired.y,ground.y+Math.max(.08,4*Math.pow(1-movement,1.5)));
      orientation.copy(state.rotation).slerp(aimed.identity(),smooth(movement/.85));
      if(movement<.85&&!reduced){euler.set(Math.sin(movement*8)*.025*(1-movement),0,Math.sin(movement*11)*.018*(1-movement));orientation.multiply(aimed.setFromEuler(euler));}
      const settle=smooth((progress*LANDING_TIME-(LANDING_TIME-1)));
      power=(.35+.45*(1-movement))*(1-settle);
      if(progress>=1){desired.set(point.x,point.y,point.z);orientation.identity();active=false;}
    }else if(action==='launching'){
      progress=reduced?1:Math.min(state.elapsed/LAUNCH_TIME,1);
      desired.set(state.start.x,THREE.MathUtils.lerp(state.start.y,route.cruiseY,smooth(Math.pow(progress,1.4))),state.start.z);
      orientation.copy(state.rotation).slerp(new THREE.Quaternion(),smooth(progress));power=.8-.25*progress;
    }else if(action==='flying'){
      if(state.groundEntry&&state.elapsed<LAUNCH_TIME&&!reduced){progress=Math.min(state.elapsed/LAUNCH_TIME,1);desired.set(state.start.x,THREE.MathUtils.lerp(state.start.y,route.cruiseY,smooth(progress)),state.start.z);orientation.identity();power=.7;}
      else if(reduced){desired.set(point.x,route.cruiseY,point.z);orientation.identity();active=false;power=0;}
      else{
        if(route.radius===0&&!frozen)block('Bu nuqta atrofida parvoz yo‘li uchun yaroqli DEM yetarli emas. Boshqa nuqtani tanlang yoki qo‘nishni boshlang.');
        if(!frozen&&!state.blocked)state.orbit+=Math.min(dt,.1)*.145*smooth((state.elapsed-(state.groundEntry?LAUNCH_TIME:0))/2.5);
        const offset=orbitOffset(state.orbit,route.radius);desired.set(point.x+offset.x,route.cruiseY+Math.sin(state.orbit*.8)*1.5,point.z+offset.z);
        const heading=Math.atan2(Math.cos(state.orbit),1.16*Math.cos(state.orbit*2));
        euler.set(Math.sin(state.orbit)*.035,heading,-Math.cos(state.orbit)*.035);aimed.setFromEuler(euler);orientation.copy(pose.quaternion).slerp(aimed,.07);power=.28;
      }
    }
    if(!frozen||reduced){
      const ground=sampleTerrain(data,desired.x,desired.z);
      if(ground){pose.position.copy(desired);pose.quaternion.copy(orientation);pose.altitude=Math.max(0,desired.y-ground.y);}
      else{block('Parvoz yo‘lida DEM ma’lumoti yo‘q. Harakat to‘xtatildi; boshqa nuqtani tanlang.');power=.22;active=false;}
    }
    pose.phaseProgress=progress;pose.moving=active&&!frozen&&!state.blocked;pose.orbitPhase=state.orbit;
    const touching=action==='placed'||!spec.canFly||((action==='landing'||action==='launching'||action==='flying')&&pose.altitude<4);
    if(touching!==groundedRef.current){groundedRef.current=touching;setGrounded(touching);}
    craft.current.position.copy(pose.position);craft.current.quaternion.copy(pose.quaternion);
    const rocket=kind==='rocket',exit=rocket?1.25:.55,maxLength=rocket?9:2.2;
    const flameLength=Math.max(.05,Math.min(maxLength,pose.altitude+exit-.05));
    if(engine.current){engine.current.visible=power>0&&!reduced;engine.current.position.y=exit;engine.current.scale.set(rocket?1:.35,flameLength/maxLength,rocket?1:.35);}
    const shimmer=.94+.06*Math.sin(state.elapsed*38);
    exhaust.outer.opacity=Math.min(1,power*.85)*shimmer;exhaust.core.opacity=Math.min(1,power*1.35)*shimmer;exhaust.jets.opacity=Math.min(1,power*1.15)*shimmer;
    if(engineLight.current)engineLight.current.intensity=power*(rocket?16:4);
    if(dust.current){
      const strength=power*THREE.MathUtils.clamp(1-pose.altitude/12,0,1);
      dust.current.visible=strength>.02&&!reduced;
      if(dust.current.visible){const positions=dustGeometry.attributes.position as THREE.BufferAttribute;
        for(let i=0;i<48;i++){const age=(state.elapsed*.55+i*.618034)%1,angle=i*2.399963;const distance=(rocket?2:1)+age*(rocket?15:6);const x=pose.position.x+Math.cos(angle)*distance,z=pose.position.z+Math.sin(angle)*distance;const ground=sampleTerrain(data,x,z);positions.setXYZ(i,x,(ground?.y??point.y)+.18+Math.sin(age*Math.PI)*(rocket?1.6:.6),z);}
        positions.needsUpdate=true;const material=dust.current.material as THREE.PointsMaterial;material.opacity=strength*.32;material.size=rocket?4.5:1.5;
      }
    }
    if(!frozen&&!state.reported&&progress>=1&&(action==='landing'||action==='launching')){state.reported=true;callback.current(action==='landing'?'placed':'flying');}
  });

  const maxFlame=kind==='rocket'?9:2.2;
  return <>
    <group ref={craft} position={poseRef.current.initialized?poseRef.current.position:[point.x,point.y,point.z]}>
      <MissionModels data={data} point={point} feet={point.feet} kind={kind} grounded={grounded} motionPaused={paused}/>
      <group ref={engine} visible={false}>
        {[0,1,2].map(i=><mesh key={`outer-${i}`} position={[0,-maxFlame/2,0]} rotation={[0,i*Math.PI/3,0]} material={exhaust.outer}><planeGeometry args={[2.9,maxFlame]}/></mesh>)}
        {[0,1].map(i=><mesh key={`core-${i}`} position={[0,-maxFlame*.3,0]} rotation={[0,Math.PI/4+i*Math.PI/2,0]} material={exhaust.core}><planeGeometry args={[.9,maxFlame*.6]}/></mesh>)}
        {kind==='rocket'&&[0,1,2].map(i=><group key={i} position={[Math.sin(i*Math.PI*2/3)*.62,-maxFlame*.23,Math.cos(i*Math.PI*2/3)*.62]}>{[0,1].map(j=><mesh key={j} rotation={[0,j*Math.PI/2,0]} material={exhaust.jets}><planeGeometry args={[.6,maxFlame*.46]}/></mesh>)}</group>)}
      </group>
      <pointLight ref={engineLight} position={[0,.8,0]} color="#a0c6ff" intensity={0} distance={25} decay={2}/>
    </group>
    <points ref={dust} geometry={dustGeometry} frustumCulled={false} visible={false}><pointsMaterial map={dustMap} color={String(data.body)==='moon'?'#aaa8a0':'#b49b7f'} size={4.5} transparent opacity={0} depthWrite={false} sizeAttenuation/></points>
  </>;
}

type CameraProps={data:TerrainData;point:MissionPoint|null;kind:ApparatusKind;view:MissionView;command:number;run:number;action:MissionAction;paused:boolean;reduced:boolean;poseRef:MutableRefObject<FlightPose>};
export function MissionCameraRig({data,point,kind,view,command,run,action,paused,reduced,poseRef}:CameraProps){
  const {camera,size,invalidate}=useThree(),controls=useRef<any>(null),manual=useRef(false),elapsed=useRef(2);
  const from=useRef(new THREE.Vector3()),lookFrom=useRef(new THREE.Vector3()),desired=useMemo(()=>new THREE.Vector3(),[]),target=useMemo(()=>new THREE.Vector3(),[]);
  const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),spec=APPARATUS_SPECS[kind];
  const previousCraft=useRef(new THREE.Vector3());
  const extent=Math.max(data.width,data.height)*data.pixel_size_m;
  const moving=action==='landing'||action==='launching'||action==='flying';
  const schedule=()=>{if(!timer.current&&!document.hidden&&!paused)timer.current=setTimeout(()=>{timer.current=undefined;invalidate();},1000/30);};
  const clearance=(position:THREE.Vector3)=>{const ground=sampleTerrain(data,position.x,position.z);if(ground)position.y=Math.max(position.y,ground.y+Math.max(1.5,spec.height*.12));};
  const framing=()=>{
    if(view==='close'&&point){
      const base=poseRef.current.initialized?poseRef.current.position:new THREE.Vector3(point.x,point.y,point.z);
      const fov=camera instanceof THREE.PerspectiveCamera?camera.fov:43,half=Math.tan(THREE.MathUtils.degToRad(fov/2)),aspect=Math.max(.3,size.width/Math.max(size.height,1));
      const width=kind==='rocket'?9.2:kind==='lander'?6:3.2;
      const distance=Math.max(spec.height/(2*half*.62),width/(2*half*aspect*.76),kind==='rocket'?32:7);
      target.copy(base).y+=spec.focusHeight;desired.copy(target).add(new THREE.Vector3(.57,.19,.8).normalize().multiplyScalar(distance));clearance(desired);
    }else{desired.set(extent*.64,extent*.58,extent*.76);target.set(0,0,0);}
  };
  useEffect(()=>{
    if(!controls.current)return;
    from.current.copy(camera.position);lookFrom.current.copy(controls.current.target);manual.current=false;elapsed.current=reduced||paused?1.15:0;previousCraft.current.copy(poseRef.current.position);
    camera.near=view==='close'?.1:Math.max(.5,extent/100000);camera.far=Math.max(30000,extent*8);
    if(camera instanceof THREE.PerspectiveCamera)camera.updateProjectionMatrix();
    framing();const catchAirborne=view==='close'&&action==='landing'&&Math.abs(camera.position.y-poseRef.current.position.y)>spec.height*2;
    if(reduced||paused||catchAirborne){camera.position.copy(desired);controls.current.target.copy(target);controls.current.update();elapsed.current=1.15;}invalidate();
  },[camera,command,run,view,point,kind,reduced,size.width,size.height,extent,invalidate]);
  useEffect(()=>{const resume=()=>{if(!document.hidden&&!paused)invalidate();};document.addEventListener('visibilitychange',resume);resume();return()=>{document.removeEventListener('visibilitychange',resume);clearTimeout(timer.current);timer.current=undefined;};},[paused,invalidate]);
  useEffect(()=>{
    if(!paused||view!=='close'||manual.current||!controls.current)return;
    // Pause may happen before the initial fly-in catches the airborne craft.
    // Finish only automatic framing; a manually chosen orbit stays untouched.
    framing();camera.position.copy(desired);controls.current.target.copy(target);
    clearance(camera.position);controls.current.update();elapsed.current=1.15;
    previousCraft.current.copy(poseRef.current.position);invalidate();
  },[paused,view,camera,invalidate]);
  useFrame((_,dt)=>{
    if(!controls.current||document.hidden)return;
    const craftDelta=poseRef.current.position.clone().sub(previousCraft.current);previousCraft.current.copy(poseRef.current.position);
    if(manual.current){if(view==='close'&&!paused){camera.position.add(craftDelta);controls.current.target.add(craftDelta);}clearance(camera.position);controls.current.update();return;}
    if(paused){clearance(camera.position);controls.current.update();return;}
    framing();const transitioning=elapsed.current<1.15;
    if(transitioning){elapsed.current+=Math.min(dt,.1);const t=smooth(elapsed.current/1.15);camera.position.lerpVectors(from.current,desired,t);controls.current.target.lerpVectors(lookFrom.current,target,t);}
    else {const blend=reduced?1:1-Math.exp(-Math.min(dt,.1)*6);camera.position.lerp(desired,blend);controls.current.target.lerp(target,blend);}
    clearance(camera.position);controls.current.update();
    // The parent owns the continuous 30 fps flight pump; camera schedules only finite transitions/settling.
    if(!moving&&(transitioning||camera.position.distanceToSquared(desired)>.0001||controls.current.target.distanceToSquared(target)>.0001))schedule();
  });
  return <OrbitControls ref={controls} makeDefault enableDamping={false} minDistance={view==='close'?Math.max(2,spec.height*.7):extent*.12} maxDistance={extent*3} maxPolarAngle={Math.PI*.495} onStart={()=>{manual.current=true;elapsed.current=2;clearTimeout(timer.current);timer.current=undefined;}}/>;
}

export default MissionFlight;
