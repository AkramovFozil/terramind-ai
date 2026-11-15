import React from 'react';
import ReactDOM from 'react-dom/client';
import {I18nProvider,useI18n} from './i18n';
const OrbitalLanding=React.lazy(()=>import('./OrbitalLanding'));
const ExplorerApp=React.lazy(()=>import('./ExplorerApp'));
const Studio=React.lazy(async()=>{await import('./styles.css');return import('./App')});
const query = new URLSearchParams(window.location.search);
function LoadingApp(){const {t}=useI18n();return <p role="status" style={{padding:32,color:'#d7e9ef',background:'#050a10',minHeight:'100vh',margin:0}}>{t({ru:'Загрузка TerraMind…',en:'Loading TerraMind…',uz:'TerraMind yuklanmoqda…'})}</p>;}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><I18nProvider><React.Suspense fallback={<LoadingApp/>}>{query.has('studio')?<Studio/>:query.has('explore')?<ExplorerApp/>:<OrbitalLanding/>}</React.Suspense></I18nProvider></React.StrictMode>,
);
