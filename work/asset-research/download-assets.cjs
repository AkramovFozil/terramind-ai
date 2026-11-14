const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve('web/public/textures');
const cache = path.resolve('work/asset-research');

async function main() {
  const jobs = [];
  for (const group of ['rock', 'sand']) {
    const metadata = JSON.parse(await fs.readFile(path.join(cache, group + '.json'), 'utf8'));
    for (const [channel, suffix] of [['Diffuse','color'],['nor_gl','normal'],['Rough','roughness']]) {
      const entry = metadata[channel]['2k'].jpg;
      jobs.push({url:entry.url, file:path.join(root,'terrain',`${group}-${suffix}.jpg`), md5:entry.md5, max:6_000_000});
    }
  }
  const base = 'https://www.solarsystemscope.com/textures/download/';
  for (const [source,file] of [
    ['8k_earth_daymap.jpg','earth-day.jpg'],
    ['2k_earth_nightmap.jpg','earth-night.jpg'],
    ['8k_mars.jpg','mars-color.jpg']
  ]) jobs.push({url:base+source,file:path.join(root,'planets',file),max:16_000_000});
  for (const [source,file] of [
    ['2k_earth_clouds.jpg','earth-clouds-source.jpg'],
    ['2k_earth_normal_map.tif','earth-normal-source.tif'],
    ['2k_earth_specular_map.tif','earth-specular-source.tif']
  ]) jobs.push({url:base+source,file:path.join(cache,file),max:16_000_000});
  const results = [];
  async function worker() {
    while(jobs.length) {
      const job = jobs.shift();
      const response = await fetch(job.url, {signal:AbortSignal.timeout(45000)});
      if(!response.ok) throw new Error(`${response.status}: ${job.url}`);
      const bytes = Buffer.from(await response.arrayBuffer());
      if(bytes.length > job.max) throw new Error('Oversized asset: '+job.file);
      const magic = bytes.subarray(0,4).toString('hex');
      if(!magic.startsWith('ffd8') && !['49492a00','4d4d002a'].includes(magic)) throw new Error('Unexpected asset format: '+job.file+' '+magic);
      if(job.md5 && crypto.createHash('md5').update(bytes).digest('hex')!==job.md5) throw new Error('Checksum mismatch: '+job.file);
      await fs.mkdir(path.dirname(job.file),{recursive:true});
      await fs.writeFile(job.file,bytes);
      const result={url:job.url,file:job.file,bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
      results.push(result); console.log(path.relative(root,job.file),bytes.length);
    }
  }
  await Promise.all([worker(),worker(),worker()]);
  await fs.writeFile(path.join(cache,'download-manifest.json'),JSON.stringify(results,null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1});
