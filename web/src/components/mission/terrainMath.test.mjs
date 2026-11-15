import test from 'node:test';
import assert from 'node:assert/strict';
import {sampleTerrain,missionPoint,initialMissionPoint} from './terrainMath.ts';
function dem(values=[0,10,20,30]){return {measured_dem:true,width:2,height:2,pixel_size_m:10,elevations:values,roi_mask:[true,true,true,true],median_elevation_m:15};}
test('interpolation follows the actual split triangles, including the diagonal',()=>{
  const d=dem([0,10,20,80]);
  assert.equal(sampleTerrain(d,-2.5,-2.5).elevation,7.5);
  assert.equal(sampleTerrain(d,2.5,2.5).elevation,47.5);
  assert.equal(sampleTerrain(d,0,0).elevation,15);
  assert.equal(sampleTerrain(d,5,5).elevation,80);
});
test('holes and ROI masks invalidate only their rendered triangle, with no fabricated bridge',()=>{
  const d=dem([0,10,20,null]);
  assert.ok(sampleTerrain(d,-3,-3));
  assert.equal(sampleTerrain(d,3,3),null);
  d.roi_mask[0]=false;
  assert.equal(sampleTerrain(d,-3,-3),null);
});
test('out-of-bounds and malformed data reject placement',()=>{
  assert.equal(sampleTerrain(dem(),5.01,0),null);
  assert.equal(sampleTerrain(dem(),NaN,0),null);
  assert.equal(sampleTerrain({...dem(),measured_dem:false},0,0),null);
  assert.equal(sampleTerrain({...dem(),pixel_size_m:0},0,0),null);
});
test('footprint must remain entirely on valid measured terrain',()=>{
  assert.ok(missionPoint(dem(),0,0));
  assert.equal(missionPoint(dem(),4,0),null);
  assert.equal(missionPoint(dem([0,10,20,null]),0,0),null);
});
test('normal and elevation keep metre scale without vertical exaggeration',()=>{
  const s=sampleTerrain(dem(),0,0);
  assert.equal(s.elevation,15);assert.equal(s.y,0);
  assert.ok(Math.abs(s.normal[0]+1/Math.sqrt(6))<1e-12);
  assert.ok(Math.abs(s.normal[1]-1/Math.sqrt(6))<1e-12);
  assert.ok(Math.abs(s.normal[2]+2/Math.sqrt(6))<1e-12);
});
test('a region without valid triangles has no default fabricated placement',()=>{
  assert.equal(initialMissionPoint(dem([null,null,null,null])),null);
  assert.ok(initialMissionPoint(dem()));
});
test('default placement validates the selected rocket footprint, including ROI edges',()=>{
  assert.ok(initialMissionPoint(dem(),4.4));
  assert.equal(initialMissionPoint({...dem(),pixel_size_m:8},4.4),null);
  assert.ok(initialMissionPoint({...dem(),pixel_size_m:8},1.15));
});
