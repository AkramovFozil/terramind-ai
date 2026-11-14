import { Suspense, useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, useTexture } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';
import type { SceneProps, Lighting, World } from './scene-types';
import { createTerrain, fbm, seededRandom, terrainHeight } from './terrain-utils';

const TEXTURES = [
  '/textures/terrain/rock-color.jpg', '/textures/terrain/rock-normal.jpg',
  '/textures/terrain/rock-roughness.jpg', '/textures/terrain/sand-color.jpg',
  '/textures/terrain/sand-normal.jpg', '/textures/terrain/sand-roughness.jpg',
];
const BALANCED_TEXTURES = TEXTURES.slice(0, 2);

function appearance(world: World, lighting: Lighting) {
  const earth = world === 'earth';
  if (lighting === 'blue') return {
    sky: '#101b30', horizon: earth ? '#7c90a0' : '#7a747f', fog: '#69717b',
    sun: '#b4c9e7', fill: '#647b9b', ground: '#383047', intensity: 1.7,
    sunPosition: [-100, 30, -150] as [number, number, number], exposure: 1.2,
  };
  if (lighting === 'day') return {
    sky: earth ? '#527c97' : '#817677', horizon: earth ? '#c8d1ca' : '#d7b49a',
    fog: earth ? '#b7c3be' : '#be9c82', sun: '#fff2d6', fill: earth ? '#b9c9d8' : '#dbc3af',
    ground: earth ? '#8e826e' : '#705048', intensity: 3.4,
    sunPosition: [-70, 140, 65] as [number, number, number], exposure: 1.0,
  };
  return {
    sky: earth ? '#5a6978' : '#5e565c', horizon: earth ? '#cfb79b' : '#d6aa86',
    fog: earth ? '#b4a48e' : '#b48b70', sun: '#ffd1a0', fill: '#b2a4a2',
    ground: '#54423d', intensity: 3.7,
    sunPosition: [-95, 42, -90] as [number, number, number], exposure: 1.12,
  };
}

function Atmosphere({ world, lighting }: { world: World; lighting: Lighting }) {
  const mood = appearance(world, lighting);
  const { scene, gl } = useThree();
  const skyMaterial = useMemo(() => new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      topColor: { value: new THREE.Color(mood.sky) },
      horizonColor: { value: new THREE.Color(mood.horizon) },
      sunColor: { value: new THREE.Color(mood.sun) },
      sunDirection: { value: new THREE.Vector3(...mood.sunPosition).normalize() },
      isEarth: { value: world === 'earth' ? 1 : 0 },
    },
    vertexShader: `varying vec3 vSkyDirection;
      void main() { vSkyDirection = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `
      varying vec3 vSkyDirection;
      uniform vec3 topColor, horizonColor, sunColor, sunDirection;
      uniform float isEarth;
      float hash(vec2 p) { return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }
      float noise(vec2 p) { vec2 i=floor(p),f=fract(p); f=f*f*(3.0-2.0*f); return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1)),f.x),f.y); }
      void main() {
        vec3 d=normalize(vSkyDirection);
        float h=pow(clamp(d.y,0.0,1.0),0.56);
        vec3 col=mix(horizonColor,topColor,h);
        float s=max(dot(d,sunDirection),0.0);
        col += sunColor * pow(s,14.0)*0.13;
        col += sunColor * pow(s,150.0)*0.09;
        float disc=smoothstep(0.99986,0.99996,s);
        col=mix(col,sunColor*3.5,disc);
        if(isEarth>0.5) {
          vec2 p=d.xz/max(d.y+0.13,0.1);
          float clouds=noise(p*3.0)*0.6+noise(p*7.0)*0.25+noise(p*15.0)*0.15;
          col=mix(col,horizonColor*1.16,smoothstep(0.61,0.88,clouds)*0.22*smoothstep(0.02,0.2,d.y));
        }
        gl_FragColor=vec4(col,1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  }), [world, lighting]);
  useEffect(() => {
    scene.fog = new THREE.FogExp2(mood.fog, 0.0028);
    scene.background = new THREE.Color(mood.horizon);
    gl.toneMappingExposure = mood.exposure;
    return () => { scene.fog = null; skyMaterial.dispose(); };
  }, [scene, gl, world, lighting, skyMaterial]);
  return <mesh material={skyMaterial} renderOrder={-20} frustumCulled={false}>
    <sphereGeometry args={[1100, 48, 24]} />
  </mesh>;
}

function Terrain({ world, quality, wireframe }: Pick<SceneProps, 'world' | 'quality' | 'wireframe'>) {
  const maps = useTexture(quality === 'ultra' ? TEXTURES : BALANCED_TEXTURES);
  const { gl } = useThree();
  const [rockColor, rockNormal, rockRough, sandColor, sandNormal, sandRough] = maps;
  const nearGeometry = useMemo(() => createTerrain(world, quality === 'ultra' ? 384 : 160), [world, quality]);
  const farGeometry = useMemo(() => createTerrain(world, quality === 'ultra' ? 144 : 64, 1100, true), [world, quality]);
  useEffect(() => {
    maps.forEach((map, i) => {
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.anisotropy = Math.min(quality === 'ultra' ? 8 : 2, gl.capabilities.getMaxAnisotropy());
      map.colorSpace = i === 0 || i === 3 ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      map.needsUpdate = true;
    });
  }, [maps, gl, quality]);
  useEffect(() => () => nearGeometry.dispose(), [nearGeometry]);
  useEffect(() => () => farGeometry.dispose(), [farGeometry]);
  const material = useMemo(() => {
    const m = new THREE.MeshStandardMaterial({
      map: rockColor, normalMap: rockNormal, roughnessMap: rockRough ?? null,
      normalScale: new THREE.Vector2(0.62, 0.62), roughness: 0.96,
      metalness: 0, vertexColors: true, wireframe,
    });
    if (quality === 'balanced') return m;
    m.onBeforeCompile = shader => {
      shader.uniforms.uSandColor = { value: sandColor };
      shader.uniforms.uSandNormal = { value: sandNormal };
      shader.uniforms.uSandRough = { value: sandRough };
      shader.vertexShader = `varying vec3 vTerrainPosition; varying vec3 vTerrainNormal;\n${shader.vertexShader}`;
      shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `
        #include <begin_vertex>
        vTerrainPosition = position;
        vTerrainNormal = normalize(normal);
      `);
      shader.fragmentShader = `
        varying vec3 vTerrainPosition;
        varying vec3 vTerrainNormal;
        uniform sampler2D uSandColor, uSandNormal, uSandRough;
        vec4 terrainTriplanar(sampler2D tex, vec3 p, vec3 n) {
          vec3 weights=pow(abs(n),vec3(4.0)); weights/=max(weights.x+weights.y+weights.z,0.0001);
          return texture2D(tex,p.zy)*weights.x + texture2D(tex,p.xz)*weights.y + texture2D(tex,p.xy)*weights.z;
        }
        ${shader.fragmentShader}`;
      shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
        vec3 surfaceNormal=normalize(vTerrainNormal);
        float sandBlend=smoothstep(0.68,0.97,surfaceNormal.y);
        vec3 rockSample=terrainTriplanar(map,vTerrainPosition*0.105,surfaceNormal).rgb;
        vec3 sandSample=terrainTriplanar(uSandColor,vTerrainPosition*0.16,surfaceNormal).rgb;
        vec3 detailColor=mix(rockSample,sandSample,sandBlend*0.82);
        float luminance=dot(detailColor,vec3(0.2126,0.7152,0.0722));
        diffuseColor.rgb *= mix(vec3(0.48+luminance*1.35),detailColor*1.35+0.3,0.2);
        float sediment=sin(vTerrainPosition.y*6.2+sin(vTerrainPosition.x*0.15)*0.8+sin(vTerrainPosition.z*0.11));
        diffuseColor.rgb *= 0.97+sediment*0.035*(1.0-sandBlend);
      `);
      shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_maps>', `
        #include <normal_fragment_maps>
        vec3 sandN=texture2D(uSandNormal,vTerrainPosition.xz*0.16).xyz*2.0-1.0;
        vec3 fineN=texture2D(normalMap,vTerrainPosition.xz*0.105).xyz*2.0-1.0;
        float fineHeight=mix(fineN.x+fineN.y,sandN.x+sandN.y,smoothstep(0.68,0.97,normalize(vTerrainNormal).y))*0.035;
        vec3 dp1=dFdx(-vViewPosition), dp2=dFdy(-vViewPosition);
        vec3 r1=cross(dp2,normal), r2=cross(normal,dp1);
        float det=dot(dp1,r1);
        vec3 grad=sign(det)*(dFdx(fineHeight)*r1+dFdy(fineHeight)*r2);
        normal=normalize(abs(det)*normal-grad);
      `);
      shader.fragmentShader = shader.fragmentShader.replace('#include <roughnessmap_fragment>', `
        float roughnessFactor=roughness;
        float terrainRough=terrainTriplanar(roughnessMap,vTerrainPosition*0.105,normalize(vTerrainNormal)).g;
        float sandRough=texture2D(uSandRough,vTerrainPosition.xz*0.16).g;
        roughnessFactor=clamp(mix(terrainRough,sandRough,smoothstep(0.68,0.97,normalize(vTerrainNormal).y))*0.45+0.55,0.7,1.0);
      `);
    };
    m.customProgramCacheKey = () => 'terramind-strata-v3';
    return m;
  }, [rockColor, rockNormal, rockRough, sandColor, sandNormal, sandRough, wireframe, quality]);
  useEffect(() => () => material.dispose(), [material]);
  return <>
    <mesh geometry={nearGeometry} material={material} receiveShadow={quality === 'ultra'} castShadow={quality === 'ultra'} />
    <mesh geometry={farGeometry} material={material} receiveShadow={quality === 'ultra'} />
    <Rocks world={world} quality={quality} colorMap={rockColor} normalMap={rockNormal} roughnessMap={rockRough} wireframe={wireframe} />
  </>;
}

function Rocks({ world, quality, colorMap, normalMap, roughnessMap, wireframe }: {
  world: World; quality: SceneProps['quality']; colorMap: THREE.Texture;
  normalMap: THREE.Texture; roughnessMap: THREE.Texture; wireframe: boolean;
}) {
  const count = quality === 'ultra' ? 900 : 220;
  const instance = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => {
    const geo = new THREE.IcosahedronGeometry(1, quality === 'ultra' ? 1 : 0);
    const pos = geo.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const d = 0.78 + fbm(x * 3 + 18, z * 3 + y) * 0.48;
      pos.setXYZ(i, x * d, y * d * 0.68, z * d);
    }
    geo.computeVertexNormals();
    return geo;
  }, [quality]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => {
    if (!instance.current) return;
    const random = seededRandom(44773), object = new THREE.Object3D(), color = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const x = (random() - 0.5) * 235, z = (random() - 0.5) * 230;
      const y = terrainHeight(x, z, world);
      const large = i % 31 === 0;
      const s = large ? 1.8 + random() * 2.8 : 0.13 + Math.pow(random(), 2.1) * 1.25;
      object.position.set(x, y + s * 0.24, z);
      object.rotation.set(random() * 0.3, random() * Math.PI * 2, random() * 0.3);
      object.scale.set(s * (0.8 + random() * 0.7), s * (0.55 + random() * 0.65), s);
      object.updateMatrix();
      instance.current.setMatrixAt(i, object.matrix);
      color.set(world === 'earth' ? '#cdbfa7' : '#b99173').multiplyScalar(0.78 + random() * 0.55);
      instance.current.setColorAt(i, color);
    }
    instance.current.instanceMatrix.needsUpdate = true;
    if (instance.current.instanceColor) instance.current.instanceColor.needsUpdate = true;
    instance.current.computeBoundingSphere();
  }, [world, count]);
  return <instancedMesh ref={instance} args={[geometry, undefined, count]} castShadow={quality === 'ultra'} receiveShadow={quality === 'ultra'}>
    <meshStandardMaterial map={colorMap} normalMap={normalMap} roughnessMap={roughnessMap ?? null}
      normalScale={new THREE.Vector2(0.75, 0.75)} roughness={0.95} metalness={0} wireframe={wireframe} />
  </instancedMesh>;
}

const PRESETS = {
  cinematic: { position: [62, 40, 104], target: [4, 6, -36] },
  overhead: { position: [28, 160, 43], target: [4, 2, -14] },
  close: { position: [26, 3.5, 48], target: [14, 8, -34] },
};

function CameraRig({ cameraPreset, autoRotate, world }: Pick<SceneProps, 'cameraPreset' | 'autoRotate' | 'world'>) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera, invalidate } = useThree();
  const transition = useRef(true);
  const destination = useRef(new THREE.Vector3());
  const target = useRef(new THREE.Vector3());
  useEffect(() => {
    const view = PRESETS[cameraPreset];
    destination.current.fromArray(view.position);
    target.current.fromArray(view.target);
    const minY = terrainHeight(destination.current.x, destination.current.z, world) + 4;
    destination.current.y = Math.max(destination.current.y, minY);
    transition.current = true;
    invalidate();
  }, [cameraPreset, world, invalidate]);
  useEffect(() => { invalidate(); }, [autoRotate, invalidate]);
  useFrame((_, delta) => {
    if (!controls.current) return;
    if (transition.current) {
      const t = 1 - Math.exp(-Math.min(delta, 0.05) * 3.6);
      camera.position.lerp(destination.current, t);
      controls.current.target.lerp(target.current, t);
      controls.current.update();
      if (camera.position.distanceTo(destination.current) < 0.035) transition.current = false;
      else invalidate();
    }
    const floor = terrainHeight(camera.position.x, camera.position.z, world) + 1.8;
    if (camera.position.y < floor - 0.02) {
      camera.position.y += Math.min((floor - camera.position.y) * Math.min(delta, 0.05) * 5, 3);
      invalidate();
    }
    if (autoRotate) invalidate();
  });
  return <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.07}
    minDistance={10} maxDistance={240} maxPolarAngle={Math.PI * 0.485} minPolarAngle={0.06}
    enablePan panSpeed={0.55} rotateSpeed={0.44} zoomSpeed={0.7}
    autoRotate={autoRotate} autoRotateSpeed={0.22}
    onStart={() => { transition.current = false; }} />;
}

function Landscape(props: SceneProps) {
  const mood = appearance(props.world, props.lighting);
  useEffect(() => { props.onReady?.(); }, [props.onReady, props.world]);
  return <>
    <Atmosphere world={props.world} lighting={props.lighting} />
    <hemisphereLight args={[mood.fill, mood.ground, props.lighting === 'blue' ? 1.05 : 1.2]} />
    <directionalLight position={mood.sunPosition} color={mood.sun} intensity={mood.intensity}
      castShadow={props.quality === 'ultra'} shadow-mapSize={[2048, 2048]}
      shadow-camera-left={-140} shadow-camera-right={140} shadow-camera-top={140} shadow-camera-bottom={-140}
      shadow-camera-near={1} shadow-camera-far={430} shadow-bias={-0.00035} shadow-normalBias={0.45}
      shadow-radius={3} />
    <directionalLight position={[70, 45, 80]} color={props.world === 'earth' ? '#9eb8d2' : '#c3a49a'} intensity={0.28} />
    <Terrain world={props.world} quality={props.quality} wireframe={props.wireframe} />
    <CameraRig cameraPreset={props.cameraPreset} autoRotate={props.autoRotate} world={props.world} />
  </>;
}

export default function TerrainScene(props: SceneProps) {
  return <Canvas frameloop="demand" shadows={props.quality === 'ultra' ? { type: THREE.PCFShadowMap } : false}
    camera={{ position: [62, 40, 104], fov: 49, near: 0.15, far: 1700 }}
    dpr={props.quality === 'ultra' ? [1, 1.65] : 1}
    gl={{ antialias: true, alpha: false, powerPreference: 'high-performance', toneMapping: THREE.ACESFilmicToneMapping }}
    style={{ width: '100%', height: '100%' }}>
    <Suspense fallback={null}><Landscape {...props} /></Suspense>
  </Canvas>;
}
