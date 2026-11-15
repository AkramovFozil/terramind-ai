import {useI18n,type Language} from '../i18n';
import './language-switcher.css';

const choices:{language:Language;name:string;label:string}[]=[{language:'ru',name:'Русский',label:'RU'},{language:'en',name:'English',label:'EN'},{language:'uz',name:'O‘zbekcha',label:'UZ'}];

export default function LanguageSwitcher({className=''}:{className?:string}){
  const {language,setLanguage,t}=useI18n();
  return <div className={`tm-language-switcher ${className}`} role="group" aria-label={t({ru:'Язык интерфейса',en:'Interface language',uz:'Interfeys tili'})}>
    {choices.map(choice=><button key={choice.language} type="button" className="tm-language-option" lang={choice.language} title={choice.name} aria-label={choice.name} aria-pressed={language===choice.language} onClick={()=>setLanguage(choice.language)}>{choice.label}</button>)}
  </div>;
}
