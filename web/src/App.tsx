import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUpRight, Check, ChevronDown, Compass, Focus, Globe2, Info, Layers3, Maximize2, Mountain, Pause, Play, RotateCcw, Sparkles, Sun, Sunrise, View, X } from 'lucide-react';
import type { CameraPreset, Lighting, Quality, ViewMode, World } from './components/scene-types';

const TerrainScene = lazy(() => import('./components/TerrainScene'));
const PlanetScene = lazy(() => import('./components/PlanetScene'));

class SceneErrorBoundary extends Component<{children: ReactNode; onReset: () => void}, {error: string | null}> {
  state = { error: null as string | null };
  static getDerivedStateFromError(error: Error) { return {error: error.message}; }
  render() {
    if (this.state.error) return <div className="scene-error"><Mountain size={34}/><h2>The scene couldn’t load.</h2><p>Check that hardware acceleration is enabled in your browser, then try again.</p><button onClick={() => {this.setState({error:null}); this.props.onReset();}}>Reload 3D scene</button><details><summary>Technical details</summary>{this.state.error}</details></div>;
    return this.props.children;
  }
}

function BrandMark() {
  return <svg width="39" height="35" viewBox="0 0 48 40" fill="none" aria-hidden="true"><path d="M3 31 17 6l12 21 7-12 10 16H3Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"/><path d="m9 31 8-13 7 13" stroke="currentColor" strokeWidth="1.3"/><circle cx="35" cy="6" r="2.7" fill="currentColor"/></svg>;
}

const presets: {id: CameraPreset; name: string; icon: typeof Compass}[] = [
  {id:'cinematic',name:'Cinematic',icon:Compass},
  {id:'overhead',name:'Survey',icon:View},
  {id:'close',name:'Close-up',icon:Focus},
];

export default function App() {
  const [world,setWorld] = useState<World>('mars');
  const [mode,setMode] = useState<ViewMode>('surface');
  const [cameraPreset,setCameraPreset] = useState<CameraPreset>('cinematic');
  const [lighting,setLighting] = useState<Lighting>('golden');
  const [quality,setQuality] = useState<Quality>('balanced');
  const [autoRotate,setAutoRotate] = useState(false);
  const [wireframe,setWireframe] = useState(false);
  const [ready,setReady] = useState(false);
  const [about,setAbout] = useState(false);
  const [settings,setSettings] = useState(false);
  const [sceneKey,setSceneKey] = useState(0);
  const [toast,setToast] = useState('');
  const [intro,setIntro] = useState(true);
  const aboutClose = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement|null>(null);
  const readyCallback = useCallback(() => { requestAnimationFrame(() => setReady(true)); },[]);
  const resetScene = useCallback(() => {setReady(false);setSceneKey(k=>k+1);},[]);

  useEffect(() => {setReady(false);setIntro(true);},[world,mode]);
  useEffect(() => {if (!toast) return; const t=setTimeout(()=>setToast(''),2800); return()=>clearTimeout(t);},[toast]);
  useEffect(() => {
    if (!about) return;
    previousFocus.current = document.activeElement as HTMLElement;
    aboutClose.current?.focus();
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setAbout(false);};
    window.addEventListener('keydown',key);
    return()=>{window.removeEventListener('keydown',key);previousFocus.current?.focus();};
  },[about]);
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setSettings(false);};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[]);

  const changePreset=(preset:CameraPreset)=>{setCameraPreset(preset);setIntro(preset==='cinematic');};
  const fullscreen=async()=>{try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen();else await document.exitFullscreen();}catch{setToast('Fullscreen is not available in this browser.');}};
  const worldName=world==='mars'?'Mars':'Earth';
  const sceneProps={world,cameraPreset,lighting,quality,autoRotate,wireframe,onReady:readyCallback};

  return <main className={`studio ${world} ${mode} quality-${quality} ${ready?'is-ready':''}`}>
    <div className="scene-stage" aria-label={`Interactive 3D ${worldName} ${mode} scene. Drag to orbit, scroll to zoom.`}>
      <SceneErrorBoundary onReset={resetScene}>
        <Suspense fallback={null}>
          {mode==='surface'?<TerrainScene key={`terrain-${sceneKey}`} {...sceneProps}/>:<PlanetScene key={`planet-${sceneKey}`} {...sceneProps}/>}
        </Suspense>
      </SceneErrorBoundary>
    </div>
    <div className="scene-shade" aria-hidden="true"/>
    <div className="grain" aria-hidden="true"/>
    {!ready&&<div className="loading-scene" role="status"><span className="loading-orbit"/><span>PREPARING YOUR EXPEDITION</span><p>Building light, atmosphere & terrain</p></div>}

    <header className="topbar">
      <button className="brand" onClick={()=>{setMode('surface');setWorld('mars');changePreset('cinematic');}} aria-label="TerraMind home"><BrandMark/><span>TerraMind<span className="brand-ai">AI</span></span></button>
      <span className="brand-divider"/>
      <span className="edition">PLANETARY<br/>FIELD LAB — 001</span>
      <nav className="view-switch" aria-label="Scene view">
        <button aria-pressed={mode==='surface'} onClick={()=>setMode('surface')}><Mountain size={15}/>Surface</button>
        <button aria-pressed={mode==='orbit'} onClick={()=>setMode('orbit')}><Globe2 size={15}/>Orbit</button>
      </nav>
      <div className="header-right"><span className="live-indicator"><i className={ready?'live':''}/>{ready?'LIVE 3D':'LOADING'}</span><button className="about-button" onClick={()=>setAbout(true)}><span>About the demo</span><ArrowUpRight size={16}/></button></div>
    </header>

    <section className={`scene-story ${intro?'':'minimized'}`} aria-label="Selected landscape">
      <div className="eyebrow"><span className="section-number">{world==='mars'?'01':'02'}</span><span className="eyebrow-rule"/><span>{mode==='orbit'?'ORBITAL PERSPECTIVE':'SURFACE EXPEDITION'}</span></div>
      <h1 key={`${world}-${mode}`}>{mode==='orbit'?(world==='mars'?<>The red<br/><em>frontier.</em></>:<>Our pale<br/><em>blue home.</em></>):(world==='mars'?<>A world<br/><em>apart.</em></>:<>Closer than<br/><em>you think.</em></>)}</h1>
      <p className="story-description">{mode==='orbit'?'A different perspective on the worlds we explore.':world==='mars'?'Ancient ridges. Sculpted valleys.\nDiscover the beauty written in terrain.':'Vast plateaus. Quiet horizons.\nSee our home through a planetary lens.'}</p>
      <button className="explore-action" onClick={()=>{changePreset(mode==='surface'?'close':'overhead');setToast('Drag the scene to look around. Scroll to adjust your distance.');}}><span>{mode==='surface'?'Explore the landscape':'Change perspective'}</span><ArrowDown size={16}/></button>
      <div className="story-footnote"><span className="tiny-star">✦</span> {mode==='surface'?'An artistic terrain study':'An interactive planetary study'}</div>
    </section>

    <div className="scene-location" aria-hidden="true"><span>{worldName.toUpperCase()}</span><i/>{mode==='surface'?(world==='mars'?'GALE · INSPIRED TERRAIN':'USTYURT · INSPIRED TERRAIN'):'ORBITAL OBSERVATION'}</div>

    <aside className="scene-tools" aria-label="3D display controls">
      <button className={settings?'active':''} aria-label="Lighting and quality settings" title="Light & quality" aria-expanded={settings} onClick={()=>setSettings(s=>!s)}><Sun size={19}/></button>
      <button className={wireframe?'active':''} aria-label="Show terrain geometry" title="Geometry view" aria-pressed={wireframe} onClick={()=>setWireframe(w=>!w)}><Layers3 size={19}/></button>
      <span className="tool-separator"/>
      <button className={autoRotate?'active':''} aria-label={autoRotate?'Pause orbit':'Auto orbit'} title={autoRotate?'Pause orbit':'Auto orbit'} aria-pressed={autoRotate} onClick={()=>setAutoRotate(v=>!v)}>{autoRotate?<Pause size={18}/>:<Play size={18}/>}</button>
      <button aria-label="Reset camera" title="Reset camera" onClick={()=>{setCameraPreset('cinematic');setAutoRotate(false);setIntro(true);resetScene();}}><RotateCcw size={18}/></button>
      <button aria-label="Toggle fullscreen" title="Fullscreen" onClick={fullscreen}><Maximize2 size={18}/></button>
    </aside>

    {settings&&<section className="settings-panel" aria-label="Scene settings">
      <div className="panel-heading"><span>SCENE SETTINGS</span><button aria-label="Close settings" onClick={()=>setSettings(false)}><X size={16}/></button></div>
      <p className="control-label">Light & atmosphere</p>
      <div className="light-options">{([{id:'golden',name:'Golden hour',icon:Sunrise},{id:'day',name:'Daylight',icon:Sun},{id:'blue',name:'Blue hour',icon:Sparkles}] as const).map(v=><button key={v.id} aria-pressed={lighting===v.id} onClick={()=>setLighting(v.id)}><v.icon size={16}/>{v.name}{lighting===v.id&&<Check size={13}/>}</button>)}</div>
      <div className="quality-row"><label htmlFor="quality">Rendering quality</label><span><select id="quality" value={quality} onChange={e=>setQuality(e.target.value as Quality)}><option value="ultra">Ultra</option><option value="balanced">Balanced</option></select><ChevronDown size={12}/></span></div>
      <p className="settings-note">Ultra prioritizes detail. Balanced reduces GPU load.</p>
    </section>}

    <div className="landscape-caption"><span className="caption-cross">+</span><span>{world==='mars'?'THE BEAUTY IS IN THE DETAILS':'FAMILIAR GROUND. NEW PERSPECTIVE.'}</span><span className="caption-line"/></div>

    <footer className="bottom-deck">
      <div className="deck-top"><span className="deck-heading">CHOOSE YOUR WORLD</span><span className="interaction-hint"><span className="mouse-icon"/>Drag to explore<span className="hint-dot"/>Scroll to zoom</span><span className="quality-badge"><i/>{quality.toUpperCase()} DETAIL</span></div>
      <div className="deck-main">
        <div className="world-options" aria-label="World selection">
          <button className={`world-card mars-card ${world==='mars'?'selected':''}`} aria-pressed={world==='mars'} onClick={()=>setWorld('mars')}><span className="world-mini mars-mini"/><span className="world-card-text"><span className="world-kicker">01 — MARS</span><strong>{mode==='surface'?'Gale landscape':'The red planet'}</strong><span className="world-subtitle">{mode==='surface'?'A study in copper & stone':'Dust, craters & ancient terrain'}</span></span><span className="world-select-icon">{world==='mars'?<span className="selected-dot"/>:<ArrowUpRight size={17}/>}</span></button>
          <button className={`world-card earth-card ${world==='earth'?'selected':''}`} aria-pressed={world==='earth'} onClick={()=>setWorld('earth')}><span className="world-mini earth-mini"/><span className="world-card-text"><span className="world-kicker">02 — EARTH</span><strong>{mode==='surface'?'Ustyurt plateau':'Our blue planet'}</strong><span className="world-subtitle">{mode==='surface'?'A study in chalk & light':'Ocean, atmosphere & land'}</span></span><span className="world-select-icon">{world==='earth'?<span className="selected-dot"/>:<ArrowUpRight size={17}/>}</span></button>
        </div>
        <div className="camera-controls"><span className="control-label">CAMERA PERSPECTIVE</span><div className="camera-options">{presets.map(p=><button key={p.id} aria-pressed={cameraPreset===p.id} onClick={()=>changePreset(p.id)}><p.icon size={16}/><span>{p.name}</span></button>)}</div></div>
      </div>
      <div className="deck-bottom"><span>EARTH ANALOG DISCOVERY ENGINE</span><span className="prototype-note"><Info size={11}/>VISUAL PROTOTYPE · ILLUSTRATIVE TERRAIN · NO SCIENTIFIC SCORES</span><span>OXUS / 2026</span></div>
    </footer>

    {toast&&<div className="toast" role="status">{toast}</div>}
    {about&&<div className="modal-backdrop" onClick={()=>setAbout(false)}><section className="about-modal" role="dialog" aria-modal="true" aria-labelledby="about-title" onClick={e=>e.stopPropagation()} onKeyDown={e=>{if(e.key==='Tab'){const items=e.currentTarget.querySelectorAll<HTMLElement>('button,a[href]');const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}}><button className="close-modal" ref={aboutClose} aria-label="Close about dialog" onClick={()=>setAbout(false)}><X size={20}/></button><BrandMark/><span className="eyebrow">TERRAMIND / VISUAL STUDY 001</span><h2 id="about-title">A little closer<br/>to another world.</h2><p>This demo explores the visual direction for TerraMind AI: detailed terrain, planetary atmosphere and a camera you can freely control.</p><p>The surface landscapes are procedurally created artistic interpretations. They are not reconstructions of measured Gale or Ustyurt elevation data. Scientific comparisons and AI explanations will be connected in a later phase.</p><div className="about-detail"><span>Built with</span><strong>React · Three.js · WebGL</strong></div><div className="about-detail"><span>Controls</span><strong>Drag · Scroll · Camera presets</strong></div><div className="about-detail"><span>Team</span><strong>OXUS University</strong></div><p className="about-small">Planet textures: <a href="https://www.solarsystemscope.com/textures/" target="_blank" rel="noreferrer">Solar System Scope</a> (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>). Terrain materials: Poly Haven (CC0). Independent student project; no NASA affiliation or endorsement. <a href="/ASSET-CREDITS.txt" target="_blank" rel="noreferrer">Full asset credits</a>.</p></section></div>}
  </main>;
}
