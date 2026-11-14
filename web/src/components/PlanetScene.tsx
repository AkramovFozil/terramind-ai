import { useEffect, useMemo, useRef, useState, type ComponentRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import type { Quality, SceneProps, World } from './scene-types';

const PLANET_RADIUS = 2.05;
const ASSETS = '/textures/planets/';

type PlanetTextures = {
  world: World;
  color?: THREE.Texture;
  clouds?: THREE.Texture;
  normal?: THREE.Texture;
  specular?: THREE.Texture;
  ready: boolean;
};

function surfaceNoise(x: number, y: number, z: number) {
  return Math.sin(x * 5.3 + Math.sin(z * 4.7)) * Math.cos(y * 6.2 + z * 2.7)
    + Math.sin(x * 13.1 + y * 8.3) * Math.cos(z * 11.7 - y * 5.1) * 0.35
    + Math.sin(z * 31.7 + x * 26.2) * Math.cos(y * 29.2) * 0.12;
}

// A deterministic local fallback keeps the globe usable if a texture fails to load.
function makeFallbackTexture(world: World) {
  const width = 512;
  const height = 256;
  const pixels = new Uint8Array(width * height * 4);
  for (let row = 0; row < height; row++) {
    const latitude = (row / height - 0.5) * Math.PI;
    for (let col = 0; col < width; col++) {
      const longitude = col / width * Math.PI * 2;
      const x = Math.cos(latitude) * Math.cos(longitude);
      const y = Math.sin(latitude);
      const z = Math.cos(latitude) * Math.sin(longitude);
      const noise = surfaceNoise(x, y, z);
      const index = (row * width + col) * 4;
      if (world === 'earth') {
        const land = noise > 0.18;
        const ice = Math.abs(y) > 0.96 - noise * 0.025;
        pixels[index] = ice ? 208 : land ? 65 + noise * 36 : 10;
        pixels[index + 1] = ice ? 222 : land ? 78 + noise * 27 : 38 + noise * 5;
        pixels[index + 2] = ice ? 226 : land ? 45 + noise * 17 : 64 + noise * 8;
      } else {
        pixels[index] = 155 + noise * 34;
        pixels[index + 1] = 91 + noise * 25;
        pixels[index + 2] = 64 + noise * 19;
      }
      pixels[index + 3] = 255;
    }
  }
  const texture = new THREE.DataTexture(pixels, width, height);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.magFilter = THREE.LinearFilter;
  texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function usePlanetTextures(world: World, quality: Quality, anisotropy: number): PlanetTextures {
  const [textures, setTextures] = useState<PlanetTextures>({ world, ready: false });
  useEffect(() => {
    let cancelled = false;
    const owned: THREE.Texture[] = [];
    const loader = new THREE.TextureLoader();
    const entries: Array<[keyof Omit<PlanetTextures, 'world' | 'ready'>, string, boolean]> = world === 'earth'
      ? [
          ['color', quality === 'ultra' ? 'earth-day.jpg' : 'earth-day-2k.jpg', true],
          ['clouds', 'earth-clouds.png', false],
          ['normal', 'earth-normal.jpg', false],
          ['specular', 'earth-specular.jpg', false],
        ]
      : [['color', quality === 'ultra' ? 'mars-color.jpg' : 'mars-color-2k.jpg', true]];
    setTextures({ world, ready: false });
    Promise.all(entries.map(([key, path, isColor]) => new Promise<[string, THREE.Texture | undefined]>((resolve) => {
      loader.load(ASSETS + path, (texture) => {
        if (cancelled) {
          texture.dispose();
          resolve([key, undefined]);
          return;
        }
        texture.colorSpace = isColor ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        texture.anisotropy = anisotropy;
        texture.wrapS = THREE.RepeatWrapping;
        owned.push(texture);
        resolve([key, texture]);
      }, undefined, () => resolve([key, undefined]));
    }))).then((loaded) => {
      if (!cancelled) setTextures({ world, ready: true, ...Object.fromEntries(loaded) });
    });
    return () => {
      cancelled = true;
      owned.forEach((texture) => texture.dispose());
    };
  }, [world, quality, anisotropy]);
  return textures.world === world ? textures : { world, ready: false };
}

const shellVertex = `
  varying vec3 vWorldNormal;
  varying vec3 vWorldPosition;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 worldPosition = modelMatrix * vec4(position, 1.0);
    vWorldPosition = worldPosition.xyz;
    vWorldNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * worldPosition;
  }
`;

const atmosphereFragment = `
  uniform vec3 uColor;
  uniform vec3 uSun;
  uniform float uStrength;
  varying vec3 vWorldNormal;
  varying vec3 vWorldPosition;
  void main() {
    vec3 eye = normalize(cameraPosition - vWorldPosition);
    vec3 normal = normalize(vWorldNormal);
    float rim = pow(1.0 - abs(dot(normal, eye)), 4.0);
    float sun = smoothstep(-0.4, 0.7, dot(normal, normalize(uSun)));
    float glow = rim * mix(0.12, 1.0, sun) * uStrength;
    gl_FragColor = vec4(uColor * (0.72 + sun * 0.55), glow);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

const cloudFragment = `
  uniform sampler2D uClouds;
  uniform vec3 uSun;
  varying vec3 vWorldNormal;
  varying vec3 vWorldPosition;
  varying vec2 vUv;
  void main() {
    vec4 cloud = texture2D(uClouds, vUv);
    float density = dot(cloud.rgb, vec3(0.3333)) * cloud.a;
    float sun = max(dot(normalize(vWorldNormal), normalize(uSun)), 0.0);
    vec3 color = vec3(0.81, 0.87, 0.94) * (0.075 + sun * 1.65);
    gl_FragColor = vec4(color, smoothstep(0.08, 0.88, density) * 0.88);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

function Starfield({ quality }: Pick<SceneProps, 'quality'>) {
  const positions = useMemo(() => {
    const count = quality === 'ultra' ? 2100 : 500;
    const array = new Float32Array(count * 3);
    let seed = 93017;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    for (let i = 0; i < count; i++) {
      const theta = random() * Math.PI * 2;
      const y = random() * 2 - 1;
      const radius = 65 + random() * 40;
      const ring = Math.sqrt(1 - y * y);
      array.set([radius * ring * Math.cos(theta), radius * y, radius * ring * Math.sin(theta)], i * 3);
    }
    return array;
  }, [quality]);
  return (
    <points frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#b6c6df" size={0.065} sizeAttenuation transparent opacity={0.52} depthWrite={false} />
    </points>
  );
}

function Planet({ world, lighting, quality, wireframe, autoRotate, onReady }: SceneProps) {
  const { gl } = useThree();
  const textures = usePlanetTextures(world, quality, Math.min(gl.capabilities.getMaxAnisotropy(), quality === 'ultra' ? 8 : 2));
  const fallback = useMemo(() => makeFallbackTexture(world), [world]);
  const cloudsRef = useRef<THREE.Mesh>(null);
  const sunPosition = useMemo(() => new THREE.Vector3(
    lighting === 'blue' ? -5 : -4.5,
    lighting === 'day' ? 3 : 2.8,
    lighting === 'day' ? 7.5 : 4.2,
  ), [lighting]);
  const atmosphereUniforms = useMemo(() => ({
    uColor: { value: new THREE.Color(world === 'earth' ? '#4794ed' : '#c77a50') },
    uSun: { value: sunPosition },
    uStrength: { value: world === 'earth' ? 0.78 : 0.3 },
  }), [world, sunPosition]);
  const cloudUniforms = useMemo(() => ({
    uClouds: { value: textures.clouds },
    uSun: { value: sunPosition },
  }), [textures.clouds, sunPosition]);

  const geometry = useMemo(() => {
    const sphere = new THREE.SphereGeometry(PLANET_RADIUS, quality === 'ultra' ? 192 : 96, quality === 'ultra' ? 128 : 48);
    if (world === 'mars') {
      const positions = sphere.attributes.position;
      const point = new THREE.Vector3();
      for (let index = 0; index < positions.count; index++) {
        point.fromBufferAttribute(positions, index).normalize();
        const elevation = surfaceNoise(point.x * 3, point.y * 3, point.z * 3) * 0.0025;
        point.multiplyScalar(PLANET_RADIUS + elevation);
        positions.setXYZ(index, point.x, point.y, point.z);
      }
      sphere.computeVertexNormals();
    }
    return sphere;
  }, [world, quality]);

  useEffect(() => () => fallback.dispose(), [fallback]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => {
    if (textures.ready) onReady?.();
  }, [textures.ready, onReady]);
  useFrame((_, delta) => {
    if (autoRotate && cloudsRef.current) cloudsRef.current.rotation.y += Math.min(delta, 0.1) * 0.0025;
  });

  return (
    <>
      <ambientLight intensity={world === 'earth' ? 0.07 : 0.1} color="#8195b4" />
      <directionalLight position={sunPosition} intensity={lighting === 'day' ? 2.25 : 1.95} color={lighting === 'golden' ? '#ffe2c1' : lighting === 'blue' ? '#b2d1ff' : '#fff9f0'} />
      <directionalLight position={[5, -2, -5]} intensity={0.035} color="#729ad9" />
      <group rotation={[0.05, world === 'earth' ? -1.5 : 0.4, 0.13]}>
        <mesh geometry={geometry}>
          <meshPhongMaterial
            map={textures.color ?? fallback}
            color={world === 'mars' ? '#e4c6b3' : '#ffffff'}
            normalMap={world === 'earth' ? textures.normal : undefined}
            normalScale={new THREE.Vector2(0.65, 0.65)}
            bumpMap={world === 'mars' ? textures.color : undefined}
            bumpScale={0.025}
            specularMap={world === 'earth' ? textures.specular : undefined}
            specular={world === 'earth' ? '#69839a' : '#332a25'}
            shininess={world === 'earth' ? 38 : 7}
            wireframe={wireframe}
          />
        </mesh>
        {world === 'earth' && textures.clouds && !wireframe && (
          <mesh ref={cloudsRef}>
            <sphereGeometry args={[PLANET_RADIUS + 0.014, quality === 'ultra' ? 128 : 64, quality === 'ultra' ? 96 : 32]} />
            <shaderMaterial vertexShader={shellVertex} fragmentShader={cloudFragment} uniforms={cloudUniforms} transparent depthWrite={false} />
          </mesh>
        )}
      </group>
      {!wireframe && (
        <mesh>
          <sphereGeometry args={[PLANET_RADIUS + (world === 'earth' ? 0.055 : 0.035), quality === 'ultra' ? 128 : 64, quality === 'ultra' ? 96 : 32]} />
          <shaderMaterial vertexShader={shellVertex} fragmentShader={atmosphereFragment} uniforms={atmosphereUniforms} side={THREE.BackSide} transparent blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      )}
    </>
  );
}

function CameraRig({ cameraPreset, autoRotate }: Pick<SceneProps, 'cameraPreset' | 'autoRotate'>) {
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  const { camera, size, invalidate } = useThree();
  const destination = useRef(new THREE.Vector3(0, 0.65, 8.6));
  const origin = useMemo(() => new THREE.Vector3(), []);
  const moving = useRef(true);

  useEffect(() => {
    if (camera instanceof THREE.PerspectiveCamera) {
      const offset = size.width > 900 ? Math.min(180, size.width * 0.13) : size.width > 650 ? 65 : 0;
      camera.setViewOffset(size.width, size.height, -offset, size.height > 650 ? 10 : 0, size.width, size.height);
      camera.updateProjectionMatrix();
      invalidate();
    }
  }, [camera, size.width, size.height, invalidate]);

  useEffect(() => {
    if (cameraPreset === 'overhead') destination.current.set(0.2, 7.6, 4.1);
    else if (cameraPreset === 'close') destination.current.set(0.15, 0.35, 6.6);
    else destination.current.set(0, 0.65, 8.6);
    moving.current = true;
    invalidate();
  }, [cameraPreset, invalidate]);

  useFrame((_, delta) => {
    if (!moving.current) return;
    const blend = 1 - Math.exp(-Math.min(delta, 0.1) * 3.5);
    camera.position.lerp(destination.current, blend);
    controls.current?.target.lerp(origin, blend);
    controls.current?.update();
    if (camera.position.distanceTo(destination.current) < 0.015) moving.current = false;
    else invalidate();
  });

  return (
    <OrbitControls
      ref={controls}
      enableDamping
      dampingFactor={0.06}
      enablePan={false}
      minDistance={4.5}
      maxDistance={14}
      rotateSpeed={0.42}
      zoomSpeed={0.65}
      autoRotate={autoRotate}
      autoRotateSpeed={0.35}
      onChange={() => invalidate()}
      onStart={() => { moving.current = false; }}
    />
  );
}

export default function PlanetScene(props: SceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 0.65, 8.6], fov: 34, near: 0.1, far: 180 }}
      dpr={props.quality === 'ultra' ? [1, 1.7] : 1}
      frameloop={props.autoRotate ? 'always' : 'demand'}
      gl={{ antialias: props.quality === 'ultra', alpha: false, powerPreference: 'default' }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
      }}
      style={{ position: 'absolute', inset: 0, background: '#03060d' }}
      fallback={<div role="status">3D ko‘rinish uchun WebGL qo‘llab-quvvatlanadigan brauzer kerak.</div>}
    >
      <color attach="background" args={['#03060d']} />
      <Starfield quality={props.quality} />
      <Planet {...props} />
      <CameraRig cameraPreset={props.cameraPreset} autoRotate={props.autoRotate} />
    </Canvas>
  );
}
