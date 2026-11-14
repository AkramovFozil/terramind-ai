TERRAMIND AI - 3D INTERFEYS DEMOSI

ISHGA TUSHIRISH
1. ZIP faylni to'liq bitta papkaga oching.
2. RUN-DEMO.cmd faylini ikki marta bosing.
3. Brauzer avtomatik ochiladi. Server oynasini ochiq qoldiring.
   Asosiy manzil: http://127.0.0.1:3000
   3000 porti band bo'lsa, dastur 3001-3010 orasidan bo'sh port tanlaydi.
4. Ishni tugatish uchun server oynasida Ctrl+C bosing.

Python 3 talab qilinadi. Tayyor demoni ochish uchun Node.js yoki npm
paketlarini o'rnatish shart emas. Python bu kompyuterda mavjud.
Qo'lda ishga tushirish: python serve-demo.py
dist/index.html faylini bevosita ikki marta bosib ochmang: mahalliy HTTP
server 3D teksturalarni va JavaScript modullarini yuklash uchun zarur.

BOSHQARUV
- Mars / Earth: dunyoni almashtirish.
- Surface / Orbit: relyef yoki sayyora ko'rinishi.
- Sichqonchani bosib sudrash: kamerani aylantirish.
- Sichqoncha g'ildiragi: yaqinlashish va uzoqlashish.
- Camera: Cinematic, Overhead va Close-up rakurslari.
- Lighting: Golden hour, Daylight va Blue hour.
- Balanced: kuchsizroq yoki integratsiyalashgan GPU uchun boshlang'ich rejim.
- Ultra: kuchli GPU uchun ko'proq detallar va soyalar.
- Auto-rotate va Wireframe boshqaruvlari mavjud.

QAMROV
Bu ishlaydigan 3D interfeys prototipi. Mars va Ustyurt sirtlari
protsedurali badiiy talqin; haqiqiy DEM o'lchovlari emas. AI tahlili,
ilmiy taqqoslash va backend keyingi integratsiya bosqichiga tegishli.
Aniq FPS kompyuter va brauzerga bog'liq. Boshlang'ich Balanced rejimida
murakkab soyalar o'chirilgan, kamera tinch turganda render to'xtaydi.

DASTURCHILAR UCHUN
src/ - React, TypeScript va Three.js manbalari.
public/ - teksturalar, shriftlar va statik resurslar.
dist/ - tayyor production build.
package.json va package-lock.json - loyihaning paket sozlamalari.
Node.js mavjud bo'lsa: npm ci, so'ng npm run dev.
Yangi production build: npm run build.
node_modules ZIP faylga kiritilmagan.

MUALLIFLIK
Sayyora teksturalari: Solar System Scope / INOVE, CC BY 4.0.
https://www.solarsystemscope.com/textures/
https://creativecommons.org/licenses/by/4.0/
Relyef materiallari: Poly Haven, CC0.
To'liq manbalar va o'zgarishlar: ASSET-CREDITS.txt.
Mustaqil talabalar loyihasi. NASA bilan rasmiy aloqasi yo'q.
