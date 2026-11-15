import './ai-generated-badge.css';
import {useI18n} from '../i18n';

/** The label stays above transitions and is included in captured scene screenshots. */
export default function AiGeneratedBadge({className=''}:{className?:string}){
  const {t}=useI18n();
  return <span className={`ai-generated-badge ${className}`} title={t({ru:'3D-сцена и анимация созданы с помощью ИИ. Источники научных данных и внешних моделей указаны отдельно.',en:'AI-assisted 3D scene and animation. Scientific data and external models are credited separately.',uz:'3D sahna va animatsiya AI yordamida yaratilgan. Ilmiy ma’lumotlar va tashqi modellar manbalari alohida ko‘rsatilgan.'})}>AI-generated</span>;
}
