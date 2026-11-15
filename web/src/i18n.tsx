import {createContext,useCallback,useContext,useEffect,useMemo,useState,type ReactNode} from 'react';

export type Language='ru'|'en'|'uz';
export type Messages=Record<Language,string>;
const STORAGE_KEY='terramind.language';
const LOCALES:Record<Language,string>={ru:'ru-RU',en:'en-US',uz:'uz-UZ'};
const validLanguage=(value:unknown):value is Language=>value==='ru'||value==='en'||value==='uz';
function initialLanguage():Language{
  try{const saved=localStorage.getItem(STORAGE_KEY);return validLanguage(saved)?saved:'ru';}catch{return 'ru';}
}
type I18nValue={language:Language;setLanguage:(language:Language)=>void;locale:string;t:(messages:Messages)=>string};
const I18nContext=createContext<I18nValue|null>(null);

export function I18nProvider({children}:{children:ReactNode}){
  const [language,updateLanguage]=useState<Language>(initialLanguage);
  const setLanguage=useCallback((next:Language)=>{if(validLanguage(next))updateLanguage(next);},[]);
  const t=useCallback((messages:Messages)=>messages[language],[language]);
  useEffect(()=>{
    try{localStorage.setItem(STORAGE_KEY,language);}catch{/* Language changes still work when storage is disabled. */}
    document.documentElement.lang=language;
    const query=new URLSearchParams(window.location.search);
    const title=query.has('explore')
      ? {ru:'Исследование планет',en:'Planetary Explorer',uz:'Sayyoralar tadqiqotchisi'}
      : query.has('studio')
        ? {ru:'Студия рельефа',en:'Terrain Studio',uz:'Relyef studiyasi'}
        : {ru:'Новый взгляд на космос',en:'A new perspective on space',uz:'Koinotga boshqacha nigoh'};
    document.title=`TerraMind AI — ${title[language]}`;
    document.querySelector('meta[name="description"]')?.setAttribute('content',{
      ru:'TerraMind AI — исследуйте Марс и Луну, сравнивайте рельеф Марса и Земли по реальным данным высот.',
      en:'TerraMind AI — explore Mars and the Moon, and compare Mars and Earth terrain using real elevation data.',
      uz:'TerraMind AI — Mars va Oyni o‘rganing, haqiqiy balandlik ma’lumotlari asosida Mars va Yer relyefini solishtiring.',
    }[language]);
  },[language]);
  useEffect(()=>{const sync=(event:StorageEvent)=>{if(event.key===STORAGE_KEY&&validLanguage(event.newValue))updateLanguage(event.newValue);};window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync);},[]);
  const value=useMemo(()=>({language,setLanguage,locale:LOCALES[language],t}),[language,setLanguage,t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n():I18nValue{
  const value=useContext(I18nContext);
  if(!value)throw new Error('useI18n must be used inside I18nProvider');
  return value;
}
