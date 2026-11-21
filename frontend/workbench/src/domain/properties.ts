export type Aeroway = 'taxiway' | 'runway' | 'parking_position';
export interface PropertyPatch { aeroway: Aeroway | null; name: string | null; ref: string | null }
export interface VersionedPropertyEdit { expected_revision: number; attributes: PropertyPatch }
export const aerowayTypes: readonly Aeroway[] = ['taxiway', 'runway', 'parking_position'];
export function propertyPatch(values: Record<string, string>): PropertyPatch {
  const aeroway = values.aeroway?.trim() || null;
  if (aeroway !== null && !aerowayTypes.includes(aeroway as Aeroway)) throw new Error('无效的 aeroway 类型');
  return { aeroway: aeroway as Aeroway | null, name: values.name?.trim() || null, ref: values.ref?.trim() || null };
}
export function requireRevision(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('无效的图版本');
  return value;
}
