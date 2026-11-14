import React from 'react';
import ReactDOM from 'react-dom/client';

// One platform: the AI Assistant is the front door, the Global Explorer and the design studio sit behind it.
const params=new URLSearchParams(window.location.search);
const Studio=React.lazy(async()=>{await import('./styles.css');return import('./App')});
const Explorer=React.lazy(()=>import('./ExplorerApp'));
const Assistant=React.lazy(()=>import('./AssistantApp'));
const Page=params.has('studio')?Studio:params.get('view')==='explorer'?Explorer:Assistant;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><React.Suspense fallback={<div className="boot">TerraMind AI…</div>}><Page/></React.Suspense></React.StrictMode>,
);
