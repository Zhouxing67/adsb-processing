import { test } from 'node:test';
import assert from 'node:assert/strict';
import { propertyPatch, requireRevision } from '../src/domain/properties.ts';
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
test('segment screen angle rotates arrow toward actual travel direction', () => {
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.6, 40.0])), 0);
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.5, 40.1])), -90);
 assert.equal(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.5, 39.9])), 90);
 assert.equal(Math.abs(Math.round(segmentScreenAngleDegrees([116.5, 40.0], [116.4, 40.0]))), 180);
});
