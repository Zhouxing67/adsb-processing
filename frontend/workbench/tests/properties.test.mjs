import { test } from 'node:test';
import assert from 'node:assert/strict';
import { propertyPatch, requireRevision } from '../src/domain/properties.ts';
import { popupPosition } from '../src/domain/popup-layout.ts';
import { segmentScreenAngleDegrees } from '../src/domain/geometry.ts';

test('property edits allow only the three business fields', () => {
 assert.deepEqual(propertyPatch({ aeroway: 'parking_position', name: ' A ', ref: '01', source_id: 'overwrite' }), {aeroway:'parking_position',name:'A',ref:'01'});
 assert.throws(() => propertyPatch({aeroway:'invalid'}));
 assert.deepEqual(propertyPatch({aeroway:'taxiway',name:' ',ref:''}),{aeroway:'taxiway',name:null,ref:null});
});
test('graph revision must be a nonnegative safe integer', () => {
 assert.equal(requireRevision(3),3);
 for(const value of [-1,1.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>requireRevision(value));
});
test('popup positions prefer above, flip below, and never mutate map state', () => {
 const size={width:300,height:300,gap:24};
 const viewport={x:900,y:700};const point={x:450,y:500};
 assert.deepEqual(popupPosition(point,viewport,size),{x:300,y:176});
 assert.deepEqual(popupPosition({x:450,y:80},viewport,size),{x:300,y:104});
 assert.deepEqual(point,{x:450,y:500});
 const narrow=popupPosition({x:450,y:350},{x:900,y:500},size);
 assert(narrow.x>=8);assert(Number.isFinite(narrow.y));
});
test('segment screen angle rotates arrow toward actual travel direction', () => {
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.6, 40.0])), 0);
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.5, 40.1])), -90);
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.5, 39.9])), 90);
 assert.equal(Math.abs(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.4, 40.0]))), 180);
});
