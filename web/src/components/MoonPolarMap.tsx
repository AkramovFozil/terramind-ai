import type {AiReference} from './AiPanel';

export type MoonMark={marker:{x:number;y:number};box:{x0:number;y0:number;x1:number;y1:number}};

/* Oy janubiy qutbi: LRO LOLA soyali relyefi (608 × 608 km, 80°J dan qutbgacha). Butun rasm ko'rinadi;
   istalgan joyni bosib 25 km oyna tanlanadi (onPick: rasmga nisbatan 0..1 koordinatalar). */
export default function MoonPolarMap({reference,point,onPick,busy}:{reference:AiReference|null;point?:MoonMark|null;onPick?:(x:number,y:number)=>void;busy?:boolean}){
  const map=reference?.map;
  if(!reference||!map)return <div className="moon-polar empty"><span className="science-spinner"/><p>{reference?.map_error??'Oy xaritasi yuklanmoqda…'}</p></div>;
  const {marker:m,box:b}=point??map;
  const click=(e:React.MouseEvent<HTMLDivElement>)=>{if(!onPick||busy)return;const r=e.currentTarget.getBoundingClientRect();onPick((e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height)};
  return <div className="moon-polar" aria-label={`${reference.name}, LRO LOLA janubiy qutb xaritasi`}>
    <div className={`moon-polar-img ${onPick&&!busy?'pickable':''}`} onClick={click}>
      <img src={map.image} alt="" draggable={false}/>
      <span className="moon-ring"/>
      {!point&&<span className="moon-label" style={{left:`${map.marker.x*100}%`,top:`${map.marker.y*100}%`}}>Mons Mouton</span>}
      <span className="moon-window" style={{left:`${b.x0*100}%`,top:`${b.y0*100}%`,width:`${(b.x1-b.x0)*100}%`,height:`${(b.y1-b.y0)*100}%`}}/>
      <span className="moon-pin" style={{left:`${m.x*100}%`,top:`${m.y*100}%`}}/>
    </div>
  </div>;
}
