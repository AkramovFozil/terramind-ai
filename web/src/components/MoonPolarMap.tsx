import type {AiReference} from './AiPanel';

/* Oy janubiy qutbi: LRO LOLA soyali relyefi (server tayyorlaydi), Mons Mouton va tasdiqlangan 25 km oyna belgilangan.
   Mars xaritasi bilan bir xil kartada turadi; o'lchamlar haqiqiy (rasm 608 × 608 km). */
export default function MoonPolarMap({reference}:{reference:AiReference|null}){
  const map=reference?.map;
  if(!reference||!map)return <div className="moon-polar empty"><span className="science-spinner"/><p>{reference?.map_error??'Oy xaritasi yuklanmoqda…'}</p></div>;
  const {marker:m,box:b}=map;
  const side=(b.x1-b.x0)*100;
  return <div className="moon-polar" aria-label={`${reference.name}, LRO LOLA janubiy qutb xaritasi`}>
    <div className="moon-polar-img" style={{transform:`translateY(-${Math.min(Math.max(m.y,.34),.66)*100}%)`}}>
      <img src={map.image} alt=""/>
      <span className="moon-window" style={{left:`${b.x0*100}%`,top:`${b.y0*100}%`,width:`${side}%`,height:`${(b.y1-b.y0)*100}%`}}/>
      <span className="moon-pin" style={{left:`${m.x*100}%`,top:`${m.y*100}%`}}/>
    </div>
    <span className="moon-scale">{reference.center.lat.toFixed(3)}° / {reference.center.lon.toFixed(3)}° · {reference.window_km} km oyna · LOLA 80 m</span>
  </div>;
}
