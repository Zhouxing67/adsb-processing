const paths = {
  search: ['M21 21l-5-5', 'M19 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0'],
  topology: ['M8 6h8M6 8v8m12-8v8M8 18h8', 'M3 3h5v5H3zM16 3h5v5h-5zM3 16h5v5H3zM16 16h5v5h-5z'],
  leftRail: ['M3 4h18v16H3z', 'M9 4v16'],
  rightRail: ['M3 4h18v16H3z', 'M15 4v16'],
  visibility: ['M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
  close: ['M6 6l12 12M18 6 6 18'],
  mapAdd: ['M4 6l5-2 6 2 5-2v14l-5 2-6-2-5 2z', 'M9 4v14M15 6v14', 'M18 9v6M15 12h6'],
  check: ['M5 12l4 4L19 6'],
};

export type StudioIconName = keyof typeof paths;

export function StudioIcon({ name }: { name: StudioIconName }) {
  return <svg className="studio-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name].map((path, index) => <path d={path} key={index} />)}</svg>;
}
