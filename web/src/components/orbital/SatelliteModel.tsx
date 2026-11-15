import { useEffect, useMemo } from 'react';
import { useLoader } from '@react-three/fiber';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as THREE from 'three';

/** NASA/JPL MRO model: original textured engineering illustration, 14,777 triangles. */
export default function SatelliteModel() {
  const gltf = useLoader(GLTFLoader, '/models/mro-nasa.glb');
  const model = useMemo(() => {
    const object = gltf.scene.clone(true);
    const materials = new Map<THREE.Material, THREE.Material>();
    object.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return;
      const cloneMaterial = (source: THREE.Material) => {
        if (materials.has(source)) return materials.get(source)!;
        const material = source.clone();
        if (material instanceof THREE.MeshStandardMaterial) {
          // Preserve NASA's actual color and foil normal maps; sunlight dominates.
          material.envMapIntensity = material.name.includes('foil') ? .65 : .35;
          material.emissive.set('#000000');
          if (material.name.includes('foil')) {
            material.roughness = .46;
            material.metalness = .8;
            material.normalScale.set(.85, .85);
          } else if (material.name === 'shiny_panel') {
            material.roughness = .36;
            material.metalness = .35;
          } else if (material.name.startsWith('tex_')) {
            material.roughness = .5;
            material.metalness = .28;
          } else if (material.name.includes('black')) {
            material.roughness = .74;
            material.metalness = .05;
            material.normalScale.set(.65, .65);
          }
          for (const texture of [material.map, material.normalMap]) if (texture) texture.anisotropy = 4;
        }
        materials.set(source, material);
        return material;
      };
      node.material = Array.isArray(node.material) ? node.material.map(cloneMaterial) : cloneMaterial(node.material);
      // Fully transparent helper cubes have no visible spacecraft detail.
      if (Array.isArray(node.material) ? node.material.every(m => m.name === 'transparent') : node.material.name === 'transparent') {
        // The transparent root mesh also parents the spacecraft: hide its pixels,
        // never the node, so the real child geometry remains visible.
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          material.transparent = true;
          material.opacity = 0;
          material.depthWrite = false;
          material.colorWrite = false;
        }
      }
    });
    return {object, materials};
  }, [gltf]);
  useEffect(() => () => model.materials.forEach(material => material.dispose()), [model]);
  // Source optical barrel tip (0,-.07,2.444) aligns to cinematic focus (0,.12,1.25).
  // Wingspan: 13.1804 source units x .65 = 8.5673 scene units.
  return <group scale={.65} position={[0, .1655, -.3386]}>
    <primitive object={model.object} dispose={null}/>
  </group>;
}
