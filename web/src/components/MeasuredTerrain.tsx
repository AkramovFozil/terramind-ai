import {useEffect,useMemo,useState} from 'react';
import {Canvas} from '@react-three/fiber';
import {OrbitControls} from '@react-three/drei';
import * as THREE from 'three';
import type {TerrainData} from '../science-types';

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
      shade.setHSL(data.body==='mars'?.055+.025*t:.105+.06*t,.28,data.body==='mars'?.25+.28*t:.24+.29*t);
      colors.set([shade.r,shade.g,shade.b],i*3);
      if(row<height-1&&col<width-1){const a=i,b=i+1,c=i+width,d=c+1;if(valid(a)&&valid(c)&&valid(b))indices.push(a,c,b);if(valid(b)&&valid(c)&&valid(d))indices.push(b,c,d);}
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(vertices,3));geo.setAttribute('color',new THREE.BufferAttribute(colors,3));geo.setIndex(indices);geo.computeVertexNormals();return geo;
  },[data,exaggeration]);
  useEffect(()=>()=>geometry.dispose(),[geometry]);
  return <mesh geometry={geometry}><meshStandardMaterial vertexColors roughness={1} metalness={0} side={THREE.DoubleSide}/></mesh>;
}

export default function MeasuredTerrain({url}:{url:string}){
  const [data,setData]=useState<TerrainData|null>(null),[error,setError]=useState(''),[exaggeration,setExaggeration]=useState(1);
  useEffect(()=>{const controller=new AbortController();setData(null);setError('');fetch(url,{signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error('Could not load the terrain data.');return r.json()}).then(v=>{if(!v.measured_dem)throw new Error('Measured DEM not found.');setData(v)}).catch(e=>{if(e.name!=='AbortError')setError(e.message)});return()=>controller.abort()},[url]);
  if(error)return <div className="terrain-loading error-message">{error}</div>;
  if(!data)return <div className="terrain-loading"><span className="science-spinner"/>Loading the measured elevation model…</div>;
  return <div className="measured-terrain"><Canvas frameloop="demand" dpr={1} camera={{position:[75,65,90],fov:43,near:.1,far:1000}} gl={{antialias:false,powerPreference:'default'}}><color attach="background" args={['#131918']}/><hemisphereLight args={['#f1ecdb','#353c3b',2.3]}/><directionalLight position={[-60,85,30]} intensity={3} color="#fff0d4"/><Surface data={data} exaggeration={exaggeration}/><OrbitControls makeDefault enableDamping minDistance={20} maxDistance={240} maxPolarAngle={Math.PI*.48}/><gridHelper args={[130,13,'#46534b','#242f29']} position={[0,-5,0]}/></Canvas><div className="terrain-scale"><span>{data.pixel_size_m} m / cell · {Math.round(data.min_elevation_m)}…{Math.round(data.max_elevation_m)} m</span><label>Vertical scale <select value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))}><option value={1}>1× — true ratio</option><option value={5}>5× — exaggerated</option><option value={10}>10× — exaggerated</option></select></label></div><div className="terrain-guidance">Rotate: drag · Zoom: scroll · Terrain: measured DEM, colours: elevation</div></div>;
}
