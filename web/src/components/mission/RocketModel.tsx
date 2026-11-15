import {useEffect,useLayoutEffect,useMemo,useRef} from 'react';
import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';

export const ROCKET_FOOT_CENTERS = Array.from({length:4},(_,i)=>{
  const angle=Math.PI/4+i*Math.PI/2;
  return new THREE.Vector3(Math.sin(angle)*4.05,0,Math.cos(angle)*4.05);
});
export type RocketContact = {height:number;normal:[number,number,number]};

function rocketTextures(){
  const metal=document.createElement('canvas');metal.width=1024;metal.height=1024;
  const ctx=metal.getContext('2d')!;ctx.fillStyle='#b9bdbe';ctx.fillRect(0,0,1024,1024);
  let seed=77;const rand=()=>{seed=(seed*16807)%2147483647;return seed/2147483647;};
  for(let x=0;x<1024;x++){const shade=130+rand()*95;ctx.strokeStyle=`rgba(${shade},${shade+3},${shade+5},.18)`;ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,1024);ctx.stroke();}
  for(let row=0;row<9;row++){ctx.fillStyle=row%2?'rgba(19,25,30,.045)':'rgba(255,255,255,.035)';ctx.fillRect(0,row*114,1024,113);}
  const metalMap=new THREE.CanvasTexture(metal);metalMap.colorSpace=THREE.SRGBColorSpace;metalMap.wrapS=metalMap.wrapT=THREE.RepeatWrapping;metalMap.anisotropy=4;
  const tiles=document.createElement('canvas');tiles.width=512;tiles.height=1024;const tc=tiles.getContext('2d')!;tc.fillStyle='#0a0d10';tc.fillRect(0,0,512,1024);
  for(let row=0;row<32;row++)for(let col=-1;col<17;col++){const x=col*32+(row%2)*16,y=row*32,v=32+Math.floor(rand()*13);tc.fillStyle=`rgb(${v},${v+2},${v+4})`;tc.fillRect(x+1,y+1,30,30);tc.fillStyle='rgba(160,156,145,.12)';tc.fillRect(x+2,y+2,28,1);}
  const tileMap=new THREE.CanvasTexture(tiles);tileMap.colorSpace=THREE.SRGBColorSpace;tileMap.wrapS=tileMap.wrapT=THREE.RepeatWrapping;tileMap.repeat.set(1,2);tileMap.anisotropy=4;
  const label=document.createElement('canvas');label.width=512;label.height=1024;const lc=label.getContext('2d')!;lc.clearRect(0,0,512,1024);lc.fillStyle='#e6e7e1';lc.font='600 76px sans-serif';lc.textAlign='center';lc.save();lc.translate(256,510);lc.rotate(-Math.PI/2);lc.fillText('TERRAMIND',0,0);lc.restore();lc.fillStyle='#a9b2b9';lc.font='24px monospace';lc.fillText('EXPEDITION',256,870);lc.font='bold 46px monospace';lc.fillStyle='#d2ad68';lc.fillText('TM–01',256,940);
  const labelMap=new THREE.CanvasTexture(label);labelMap.colorSpace=THREE.SRGBColorSpace;labelMap.anisotropy=4;
  return {metalMap,tileMap,labelMap};
}
function rod(a:THREE.Vector3,b:THREE.Vector3,radius:number,radiusTop=radius){const d=b.clone().sub(a);return new THREE.CylinderGeometry(radiusTop,radius,d.length(),12).applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),d.normalize())).translate(...a.clone().add(b).multiplyScalar(.5).toArray() as [number,number,number]);}
function merge(parts:THREE.BufferGeometry[]){const result=mergeGeometries(parts,false)!;parts.forEach(p=>p.dispose());return result;}
function ring(radius:number,y:number,tube=.013){return new THREE.TorusGeometry(radius,tube,6,96).rotateX(Math.PI/2).translate(0,y,0);}

function Fasteners(){
  const ref=useRef<THREE.InstancedMesh>(null);
  const poses=useMemo(()=>{const matrices:THREE.Matrix4[]=[];const up=new THREE.Vector3(0,1,0);for(const y of [3.05,4.7,6.35,8,9.65,11.3,12.95,13.75])for(let i=0;i<40;i++){const a=i*Math.PI*2/40,n=new THREE.Vector3(Math.sin(a),0,Math.cos(a)),position=n.clone().multiplyScalar(1.508);position.y=y+.04;matrices.push(new THREE.Matrix4().compose(position,new THREE.Quaternion().setFromUnitVectors(up,n),new THREE.Vector3(1,1,1)));}return matrices;},[]);
  useLayoutEffect(()=>{if(!ref.current)return;poses.forEach((matrix,i)=>ref.current!.setMatrixAt(i,matrix));ref.current.instanceMatrix.needsUpdate=true;},[poses]);
  return <instancedMesh ref={ref} args={[undefined,undefined,poses.length]}><cylinderGeometry args={[.018,.018,.011,6]}/><meshStandardMaterial color="#7e888c" metalness={.8} roughness={.4}/></instancedMesh>;
}

/** Metre-scale TerraMind concept vehicle. Four pad soles at Y=0, tip at Y=18. */
export default function RocketModel({contacts}:{contacts?:RocketContact[]}){
  const maps=useMemo(rocketTextures,[]);
  const parts=useMemo(()=>{
    const rings:THREE.BufferGeometry[]=[],silver:THREE.BufferGeometry[]=[],dark:THREE.BufferGeometry[]=[],pipes:THREE.BufferGeometry[]=[],bells:THREE.BufferGeometry[]=[],fins:THREE.BufferGeometry[]=[];
    for(const y of [2.8,3.05,4.7,6.35,8,9.65,11.3,12.95,13.75])rings.push(ring(1.504,y));
    for(let i=0;i<12;i++){const a=i*Math.PI/6,x=Math.sin(a)*1.502,z=Math.cos(a)*1.502;rings.push(rod(new THREE.Vector3(x,3.08,z),new THREE.Vector3(x,13.72,z),.005));}
    // Instrument service conduits are recessed against the cylindrical pressure shell.
    for(const x of [-.2,.2])pipes.push(rod(new THREE.Vector3(x,3.1,-1.485),new THREE.Vector3(x,11.9,-1.485),.035));
    for(const y of [4,6,8,10,11.8])silver.push(new THREE.BoxGeometry(.65,.05,.09).translate(0,y,-1.5));
    const bellProfile=[new THREE.Vector2(.32,0),new THREE.Vector2(.3,.16),new THREE.Vector2(.245,.4),new THREE.Vector2(.17,.7),new THREE.Vector2(.11,.92),new THREE.Vector2(.13,1.08)];
    for(let i=0;i<4;i++){
      const a=(i-1)*Math.PI*2/3,r=i===0?0:.62,x=Math.sin(a)*r,z=Math.cos(a)*r,scale=i===0?1:.72;
      bells.push(new THREE.LatheGeometry(bellProfile,48).scale(scale,i===0?1:.9,scale).translate(x,1.25,z));
      silver.push(new THREE.CylinderGeometry(.19*scale,.2*scale,.42,24).translate(x,2.5,z));
      for(let k=0;k<5;k++)pipes.push(new THREE.TorusGeometry((.13+k*.027)*scale,.014,6,32).rotateX(Math.PI/2).translate(x,2.15-k*.13,z));
      pipes.push(rod(new THREE.Vector3(x+.13,2.42,z),new THREE.Vector3(x+.35,2.78,z+.12),.034));
    }
    for(let i=0;i<4;i++){
      const a=Math.PI/4+i*Math.PI/2,s=Math.sin(a),c=Math.cos(a),p=(r:number,y:number,side=0)=>new THREE.Vector3(s*r+c*side,y,c*r-s*side),foot=contacts?.[i]?.height??0;
      // Twin load-bearing spars, a telescopic shock strut, and two wide clevis joints.
      for(const side of [-.1,.1])silver.push(rod(p(1.36,4.65,side),p(4.02,foot+.19,side),.075,.095));
      dark.push(rod(p(1.37,2.85),p(3.03,foot+1.02),.15,.18));
      silver.push(rod(p(2.48,1.63),p(3.97,foot+.23),.082));
      for(const [r,y] of [[1.4,4.65],[1.42,2.85],[4.02,foot+.18]])silver.push(new THREE.CylinderGeometry(.16,.16,.33,16).applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),new THREE.Vector3(c,0,-s))).translate(...p(r,y).toArray() as [number,number,number]));
      const shape=new THREE.Shape();shape.moveTo(1.46,0);shape.lineTo(2.12,.35);shape.lineTo(1.86,2.1);shape.lineTo(1.46,2.45);shape.closePath();
      const fin=new THREE.ExtrudeGeometry(shape,{depth:.09,bevelEnabled:true,bevelSize:.015,bevelThickness:.015,bevelSegments:1,steps:1}).translate(0,4.6,-.045).rotateY(Math.PI/2-a);fins.push(fin);
      dark.push(new THREE.BoxGeometry(.35,.6,.12).translate(0,12.5,1.51).rotateY(a));
    }
    return {rings:merge(rings),silver:merge(silver),dark:merge(dark),pipes:merge(pipes),bells:merge(bells),fins:merge(fins)};
  },[contacts]);
  const nose=useMemo(()=>{
    const profile=[new THREE.Vector2(1.5,13.8),new THREE.Vector2(1.5,14.05),new THREE.Vector2(1.46,14.65),new THREE.Vector2(1.34,15.3),new THREE.Vector2(1.13,16),new THREE.Vector2(.84,16.7),new THREE.Vector2(.48,17.35),new THREE.Vector2(.16,17.8),new THREE.Vector2(.012,18)];
    return new THREE.LatheGeometry(profile,80);
  },[]);
  useEffect(()=>()=>Object.values(maps).forEach(texture=>texture.dispose()),[maps]);
  useEffect(()=>()=>Object.values(parts).forEach(geometry=>geometry.dispose()),[parts]);
  useEffect(()=>()=>nose.dispose(),[nose]);
  return <group>
    <mesh position={[0,8.3,0]} castShadow receiveShadow><cylinderGeometry args={[1.5,1.5,11,80,1,true]}/><meshStandardMaterial map={maps.metalMap} color="#c5cbce" roughness={.32} metalness={.82} envMapIntensity={.85}/></mesh>
    <mesh geometry={nose} castShadow receiveShadow><meshStandardMaterial map={maps.metalMap} color="#bfc7cb" roughness={.3} metalness={.8} envMapIntensity={.85}/></mesh>
    <mesh position={[0,8.3,0]} castShadow><cylinderGeometry args={[1.507,1.507,10.95,48,1,true,Math.PI/2,Math.PI]}/><meshStandardMaterial map={maps.tileMap} bumpMap={maps.tileMap} bumpScale={.012} roughness={.95} metalness={.03}/></mesh>
    <mesh position={[0,3.2,0]} castShadow><cylinderGeometry args={[1.51,1.51,.75,80,1,true]}/><meshStandardMaterial color="#252b2f" roughness={.7} metalness={.35}/></mesh>
    <mesh position={[0,2.8,0]} rotation={[Math.PI/2,0,0]} receiveShadow><circleGeometry args={[1.49,64]}/><meshStandardMaterial color="#3a3d3d" roughness={.64} metalness={.65} side={THREE.DoubleSide}/></mesh>
    <mesh geometry={parts.rings}><meshStandardMaterial color="#646d70" roughness={.43} metalness={.76}/></mesh>
    <mesh geometry={parts.silver} castShadow><meshStandardMaterial color="#a6b2b9" roughness={.26} metalness={.86}/></mesh>
    <mesh geometry={parts.dark} castShadow><meshStandardMaterial color="#30383d" roughness={.5} metalness={.7}/></mesh>
    <mesh geometry={parts.pipes} castShadow><meshStandardMaterial color="#8c8069" roughness={.38} metalness={.8}/></mesh>
    <mesh geometry={parts.bells} castShadow><meshStandardMaterial color="#454a4c" roughness={.48} metalness={.8} side={THREE.DoubleSide}/></mesh>
    <mesh geometry={parts.fins} castShadow><meshStandardMaterial color="#656e73" roughness={.39} metalness={.8}/></mesh>
    <Fasteners/>
    <mesh position={[0,10,0]}><cylinderGeometry args={[1.512,1.512,4.3,24,1,true,-.35,.7]}/><meshBasicMaterial map={maps.labelMap} transparent depthWrite={false} polygonOffset polygonOffsetFactor={-1}/></mesh>
    {ROCKET_FOOT_CENTERS.map((foot,i)=>{const normal=new THREE.Vector3(...(contacts?.[i]?.normal??[0,1,0])),position=new THREE.Vector3(foot.x,contacts?.[i]?.height??0,foot.z).addScaledVector(normal,.08);return <mesh key={i} position={position} quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),normal)} castShadow receiveShadow><cylinderGeometry args={[.29,.35,.16,24]}/><meshStandardMaterial color="#697277" roughness={.6} metalness={.7}/></mesh>})}
  </group>;
}
