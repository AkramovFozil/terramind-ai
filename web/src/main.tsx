import React from 'react';
import ReactDOM from 'react-dom/client';
import ExplorerApp from './ExplorerApp';
const Studio=React.lazy(async()=>{await import('./styles.css');return import('./App')});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{new URLSearchParams(window.location.search).has('studio')?<React.Suspense fallback={<p>Studio yuklanmoqda…</p>}><Studio/></React.Suspense>:<ExplorerApp/>}</React.StrictMode>,
);
