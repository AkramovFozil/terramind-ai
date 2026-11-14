export type World = 'mars' | 'earth';
export type ViewMode = 'surface' | 'orbit';
export type CameraPreset = 'cinematic' | 'overhead' | 'close';
export type Lighting = 'golden' | 'day' | 'blue';
export type Quality = 'ultra' | 'balanced';

export interface SceneProps {
  world: World;
  cameraPreset: CameraPreset;
  lighting: Lighting;
  quality: Quality;
  autoRotate: boolean;
  wireframe: boolean;
  onReady?: () => void;
}
