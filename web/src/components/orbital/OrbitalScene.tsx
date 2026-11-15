import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import SatelliteModel from './SatelliteModel';
import {useI18n} from '../../i18n';

export type OrbitalSceneProps = {
  target: 'mars' | 'moon';
  phase: 'idle' | 'focus' | 'scan';
  quality: 'medium' | 'high';
  paused: boolean;
  reducedMotion: boolean;
  onReady: () => void;
  onError?: () => void;
};

const RADIUS = 2.5;
const rimVertex = `varying vec3 vNormal; varying vec3 vView;
void main(){vec4 p=modelViewMatrix*vec4(position,1.0);vNormal=normalize(normalMatrix*normal);vView=normalize(-p.xyz);gl_Position=projectionMatrix*p;}`;
const rimFragment = `varying vec3 vNormal;varying vec3 vView;uniform vec3 tint;
void main(){float edge=pow(1.0-max(dot(normalize(vNormal),normalize(vView)),0.0),4.5);gl_FragColor=vec4(tint,edge*0.32);}`;
const beamVertex = `varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`;
const beamFragment = `varying vec2 vUv;uniform float strength;void main(){float x=abs(vUv.x-.5)*2.;float edge=pow(max(0.,1.-x),2.6);float along=pow(max(0.,vUv.y),1.8)*smoothstep(0.,.08,1.-vUv.y);float streak=.78+.22*sin(vUv.x*83.);gl_FragColor=vec4(.55,.8,1.,edge*along*streak*strength);}`;

function ReflectionEnvironment() {
  const { gl, scene, invalidate } = useThree();
  useEffect(() => {
    const canvas = document.createElement('canvas'); canvas.width = 1024; canvas.height = 512;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#101824'; ctx.fillRect(0, 0, 1024, 512);
    const light = (x:number,y:number,w:number,h:number,color:string) => {
      const gradient = ctx.createRadialGradient(x,y,0,x,y,w);
      gradient.addColorStop(0,color); gradient.addColorStop(.38,color); gradient.addColorStop(1,'rgba(5,9,17,0)');
      ctx.save();ctx.translate(0,y);ctx.scale(1,h/w);ctx.translate(0,-y);ctx.fillStyle=gradient;ctx.fillRect(x-w,y-w,w*2,w*2);ctx.restore();
    };
    light(160,120,180,64,'#fff9df'); light(690,160,145,43,'#cbeaff'); light(900,330,115,90,'#6e88aa');
    ctx.fillStyle='#dae8f2';ctx.fillRect(390,85,32,220);ctx.fillStyle='#6b819b';ctx.fillRect(450,120,9,165);
    const source = new THREE.CanvasTexture(canvas); source.mapping = THREE.EquirectangularReflectionMapping; source.colorSpace=THREE.SRGBColorSpace;
    const generator = new THREE.PMREMGenerator(gl); const result = generator.fromEquirectangular(source);
    const previous = scene.environment; scene.environment=result.texture; scene.environmentIntensity=.42;
    source.dispose();generator.dispose();invalidate();
    return()=>{scene.environment=previous;result.dispose();};
  },[gl,scene,invalidate]);
  return null;
}

function CinematicRays({focus}: {focus:boolean}) {
  const uniforms = useMemo(()=>({strength:{value:focus ? .55 : .14}}),[focus]);
  const glow = useMemo(()=>{
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
    const ctx=canvas.getContext('2d')!,g=ctx.createRadialGradient(64,64,0,64,64,64);
    g.addColorStop(0,'rgba(225,246,255,.95)');g.addColorStop(.08,'rgba(190,228,255,.65)');g.addColorStop(.3,'rgba(99,181,255,.14)');g.addColorStop(1,'rgba(67,140,225,0)');ctx.fillStyle=g;ctx.fillRect(0,0,128,128);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return texture;
  },[]);
  useEffect(()=>()=>glow.dispose(),[glow]);
  return <>
    <group position={[4.7,4,-3]} rotation={[0,0,-.68]}>
      <mesh position={[0,-5,0]}><planeGeometry args={[4.8,12]}/><shaderMaterial vertexShader={beamVertex} fragmentShader={beamFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide}/></mesh>
      <sprite scale={[2.5,2.5,1]}><spriteMaterial map={glow} transparent blending={THREE.AdditiveBlending} depthWrite={false} opacity={.85}/></sprite>
    </group>
    {focus&&<>
      <mesh position={[0,.12,2.6]} rotation={[Math.PI/2,0,0]}><cylinderGeometry args={[1.5,.36,2.7,40,1,true]}/><meshBasicMaterial color="#69cbff" transparent opacity={.035} blending={THREE.AdditiveBlending} depthWrite={false} side={THREE.DoubleSide}/></mesh>
      <sprite position={[0,.12,1.31]} scale={[2.2,2.2,1]}><spriteMaterial map={glow} transparent opacity={.62} blending={THREE.AdditiveBlending} depthWrite={false}/></sprite>
    </>}
  </>;
}

function useSurfaceTexture(target: OrbitalSceneProps['target'], quality: OrbitalSceneProps['quality'], onError?: () => void) {
  const [texture, setTexture] = useState<THREE.Texture>();
  const { invalidate, gl } = useThree();
  const errorRef = useRef(onError);
  errorRef.current = onError;
  useEffect(() => {
    let cancelled = false;
    let owned: THREE.Texture | undefined;
    setTexture(undefined);
    const path = target === 'moon'
      ? `/textures/orbital/moon-${quality === 'high' ? '4k' : '2k'}.jpg`
      : `/textures/planets/mars-color${quality === 'high' ? '' : '-2k'}.jpg`;
    new THREE.TextureLoader().load(path, loaded => {
      if (cancelled) { loaded.dispose(); return; }
      owned = loaded;
      loaded.colorSpace = THREE.SRGBColorSpace;
      loaded.anisotropy = Math.min(gl.capabilities.getMaxAnisotropy(), quality === 'high' ? 8 : 2);
      setTexture(loaded);
      invalidate();
    }, undefined, () => {
      if (!cancelled) {
        // A missing source image must not look like a successfully loaded planet.
        errorRef.current?.();
        invalidate();
      }
    });
    return () => { cancelled = true; owned?.dispose(); };
  }, [target, quality, gl, invalidate]);
  return texture;
}

function globeGrid() {
  const points: number[] = [];
  const vertex = (lat: number, lng: number) => [Math.cos(lat) * Math.cos(lng) * 2.509, Math.sin(lat) * 2.509, Math.cos(lat) * Math.sin(lng) * 2.509];
  for (let lat = -60; lat <= 60; lat += 30) for (let lng = 0; lng < 360; lng += 3) points.push(...vertex(lat * Math.PI / 180, lng * Math.PI / 180), ...vertex(lat * Math.PI / 180, (lng + 3) * Math.PI / 180));
  for (let lng = 0; lng < 360; lng += 30) for (let lat = -90; lat < 90; lat += 3) points.push(...vertex(lat * Math.PI / 180, lng * Math.PI / 180), ...vertex((lat + 3) * Math.PI / 180, lng * Math.PI / 180));
  return new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
}

function SurveyGlobe({ target, quality, paused, reducedMotion, onError }: OrbitalSceneProps) {
  const texture = useSurfaceTexture(target, quality, onError);
  const globe = useRef<THREE.Group>(null);
  const sweep = useRef<THREE.Mesh>(null);
  const scanTime = useRef(0);
  const grid = useMemo(globeGrid, []);
  const uniforms = useMemo(() => ({ tint: { value: new THREE.Color(target === 'mars' ? '#d6a078' : '#8cbfd9') } }), [target]);
  useEffect(() => () => grid.dispose(), [grid]);
  useFrame((_, dt) => {
    if (paused || reducedMotion) return;
    scanTime.current += Math.min(dt, .1);
    if (globe.current) globe.current.rotation.y += Math.min(dt, .1) * .026;
    if (sweep.current) {
      const y = Math.sin(scanTime.current * .45) * 2.2;
      const scale = Math.sqrt(RADIUS * RADIUS - y * y) / RADIUS;
      sweep.current.position.y = y;
      sweep.current.scale.set(scale, scale, 1);
    }
  });
  return <group rotation={[.08, 0, -.12]}>
    <group ref={globe} rotation={[0, target === 'mars' ? .45 : -1.2, 0]}>
      <mesh>
        <sphereGeometry args={[RADIUS, quality === 'high' ? 128 : 80, quality === 'high' ? 80 : 48]}/>
        <meshStandardMaterial key={texture?.uuid ?? 'surface-loading'} map={texture} color={texture ? '#ffffff' : target === 'mars' ? '#b87f5d' : '#a8abac'} envMapIntensity={0} roughness={.96} metalness={0} bumpMap={texture} bumpScale={target === 'moon' ? .035 : .018}/>
      </mesh>
      <lineSegments geometry={grid}><lineBasicMaterial color="#8bcbd7" transparent opacity={.12} depthWrite={false}/></lineSegments>
    </group>
    <mesh scale={1.014}><sphereGeometry args={[RADIUS, 64, 40]}/><shaderMaterial vertexShader={rimVertex} fragmentShader={rimFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
    <mesh ref={sweep} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[2.524, .009, 6, 160]}/>
      <meshBasicMaterial color="#a6f6ed" transparent opacity={.85} toneMapped={false}/>
    </mesh>
    <mesh rotation={[1.02, .55, -.35]}><torusGeometry args={[2.91, .004, 5, 192]}/><meshBasicMaterial color="#98c3cd" transparent opacity={.25} depthWrite={false}/></mesh>
    <mesh rotation={[1.02, .55, -.35]} position={[0, 0, 0]}><torusGeometry args={[2.98, .002, 4, 192, Math.PI * .65]}/><meshBasicMaterial color="#d4dcd3" transparent opacity={.45}/></mesh>
  </group>;
}

/** The renderer sleeps while hidden/paused and ticks at a bounded rate during motion. */
function RenderClock({ phase, paused, reducedMotion, quality }: OrbitalSceneProps) {
  const { invalidate, size } = useThree();
  const transition = useRef({ phase, width: size.width, height: size.height, until: performance.now() + 3600 });
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    if (transition.current.phase !== phase || transition.current.width !== size.width || transition.current.height !== size.height) {
      transition.current = { phase, width: size.width, height: size.height, until: performance.now() + (reducedMotion ? 0 : 3600) };
    }
    const tick = () => {
      timer = undefined;
      if (disposed || document.hidden) return;
      const animating = !paused && !reducedMotion;
      const transitioning = !reducedMotion && performance.now() < transition.current.until;
      if (!animating && !transitioning) return;
      invalidate();
      timer = setTimeout(tick, quality === 'high' ? 1000 / 60 : 1000 / 30);
    };
    const visibility = () => {
      clearTimeout(timer);
      timer = undefined;
      if (!document.hidden) { invalidate(); tick(); }
    };
    document.addEventListener('visibilitychange', visibility);
    // Even static/reduced-motion views get one frame for a changed selection.
    if (!document.hidden) invalidate();
    tick();
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility); };
  }, [phase, paused, reducedMotion, quality, size.width, size.height, invalidate]);
  return null;
}

function OrbitalContents(props: OrbitalSceneProps) {
  const { camera, size, pointer, invalidate } = useThree();
  const satellite = useRef<THREE.Group>(null);
  const motionTime = useRef(0);
  const offset = useRef(0);
  const look = useRef(new THREE.Vector3(0, .15, 0));
  const destination = useMemo(() => new THREE.Vector3(), []);
  const desiredLook = useMemo(() => new THREE.Vector3(), []);
  const oldPhase = useRef(props.phase);
  const initialized = useRef(false);
  const transitionTime = useRef(0);
  const transitionStarted = useRef(performance.now());
  const focusStart = useRef(new THREE.Vector3());
  const focusLookStart = useRef(new THREE.Vector3());
  const focusOffset = useRef(0);
  const readyRef = useRef(props.onReady);
  readyRef.current = props.onReady;

  useEffect(() => { readyRef.current(); }, []);
  useEffect(() => {
    if(props.phase !== oldPhase.current){transitionTime.current=0;transitionStarted.current=performance.now();focusStart.current.copy(camera.position);focusLookStart.current.copy(look.current);focusOffset.current=offset.current;}
    if (props.phase === 'scan' && oldPhase.current !== 'scan') {
      camera.position.set(0, .12, props.reducedMotion ? (size.width < 760 ? 10.7 : 12.8) : 24);
      look.current.set(0, 0, 0);
    }
    oldPhase.current = props.phase;
    invalidate();
  }, [props.phase, camera, invalidate, size.width, props.reducedMotion]);

  useFrame((_, dt) => {
    const delta = Math.min(dt, .1);
    transitionTime.current = (performance.now()-transitionStarted.current)/1000;
    const blend = props.reducedMotion ? 1 : 1 - Math.exp(-delta * (props.phase === 'scan' ? 1.25 : 3.5));
    const mobile = size.width < 760;
    const aspect = size.width / Math.max(size.height, 1);
    const idleZ = Math.max(mobile ? 14.3 : 16.8, 8.8 / (2 * Math.tan(34 * Math.PI / 360) * aspect) * 1.08);
    const scanZ = Math.max(mobile ? 10.7 : 12.8, 6.2 / (2 * Math.tan(34 * Math.PI / 360) * aspect));
    destination.set(0, props.phase === 'idle' ? .9 : .12, props.phase === 'focus' ? 1.46 : props.phase === 'scan' ? scanZ : idleZ);
    desiredLook.set(0, props.phase === 'focus' ? .12 : .05, 0);
    const wantedOffset = mobile || props.phase === 'focus' ? 0 : -.205;
    if (!initialized.current) {
      camera.position.copy(destination);
      look.current.copy(desiredLook);
      offset.current = wantedOffset;
      initialized.current = true;
    } else if(props.phase === 'focus') {
      const t=props.reducedMotion?1:THREE.MathUtils.clamp(transitionTime.current/3.15,0,1);
      const ease=t*t*t*(t*(t*6-15)+10);
      camera.position.lerpVectors(focusStart.current,destination,ease);
      look.current.lerpVectors(focusLookStart.current,desiredLook,ease);
      offset.current=THREE.MathUtils.lerp(focusOffset.current,0,THREE.MathUtils.smoothstep(t,0,.65));
    } else {
      camera.position.lerp(destination, blend);
      look.current.lerp(desiredLook, blend);
    }
    camera.lookAt(look.current);
    if(props.phase!=='focus')offset.current = THREE.MathUtils.lerp(offset.current, wantedOffset, blend);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.setViewOffset(size.width, size.height, size.width * offset.current, 0, size.width, size.height);
    }
    if (!props.paused && !props.reducedMotion) motionTime.current += delta;
    const time = motionTime.current;
    if (satellite.current) {
      const active = props.phase === 'idle';
      const parallax = props.paused || props.reducedMotion ? 0 : 1;
      // NASA's solar-cell faces point toward source -Y; +Y is the black wired backing.
      satellite.current.rotation.x = THREE.MathUtils.lerp(satellite.current.rotation.x, active ? -.68 + Math.sin(time * .16) * .035 + pointer.y * .035 * parallax : 0, blend);
      satellite.current.rotation.y = THREE.MathUtils.lerp(satellite.current.rotation.y, active ? -.38 + Math.sin(time * .13) * .045 + pointer.x * .04 * parallax : 0, blend);
      satellite.current.rotation.z = THREE.MathUtils.lerp(satellite.current.rotation.z, active ? -.22 + Math.sin(time * .1) * .025 : 0, blend);
      satellite.current.position.y = THREE.MathUtils.lerp(satellite.current.position.y, active ? Math.sin(time * .4) * .09 : 0, blend);
    }
  });

  return <>
    <ReflectionEnvironment/>
    <ambientLight color="#d4dce8" intensity={props.phase === 'scan' ? .035 : .035}/>
    <hemisphereLight args={['#e5f0ff', '#67707d', props.phase === 'scan' ? .06 : .07]}/>
    <directionalLight position={props.phase === 'scan' ? [-5, 3, 4] : [-3, 1.5, 7]} color="#fff7e9" intensity={props.phase === 'scan' ? 2.7 : 3.4}/>
    <directionalLight position={[5, -.5, 3]} color="#c5d6e8" intensity={props.phase === 'scan' ? .025 : .16}/>
    <directionalLight position={[0, 3, -4]} color="#e8ecf0" intensity={props.phase === 'scan' ? .13 : .45}/>
    {props.phase!=='scan'&&<CinematicRays focus={props.phase==='focus'}/>}
    {props.phase !== 'scan' ? <group ref={satellite} rotation={[-.68, -.38, -.22]}><SatelliteModel/></group> : <SurveyGlobe {...props}/>}
    <RenderClock {...props}/>
  </>;
}

export default function OrbitalScene(props: OrbitalSceneProps) {
  const {t}=useI18n();
  return <Canvas
    camera={{ position: [0, .9, 14.3], fov: 34, near: .025, far: 80 }}
    dpr={props.quality === 'high' ? [1, 1.5] : 1}
    frameloop="demand"
    gl={{ alpha: true, antialias: true, powerPreference: 'default', stencil: false }}
    onCreated={({ gl }) => {
      gl.setClearColor(0x000000, 0);
      gl.toneMapping = THREE.ACESFilmicToneMapping;
      gl.toneMappingExposure = 1.05;
    }}
    onError={() => props.onError?.()}
    style={{ position: 'absolute', inset: 0, background: 'transparent' }}
    fallback={<div className="orbital-webgl-fallback" role="status">{t({ru:'Не удалось загрузить 3D. Вы можете продолжить исследование на карте.',en:'The 3D view could not load. You can continue exploring on the map.',uz:'3D ko‘rinish yuklanmadi. Tadqiqotni xaritada davom ettirishingiz mumkin.'})}</div>}
  ><OrbitalContents {...props}/></Canvas>;
}
