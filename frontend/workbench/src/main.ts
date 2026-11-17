import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './app.css';
import './flight-layout.css';
import './workbench.css';

// Temporary adapter while individual domain views move into React components.
Object.assign(window, { L });
async function loadBridge(name: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `/bridge/${name}`;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${name}`));
    document.body.append(script);
  });
}
try {
  await loadBridge('app.js');
  await loadBridge('flights-v2.js');
  await loadBridge('flight-workspace.js');
  await import('./shell.js');
} catch (error) {
  const status = document.getElementById('status');
  if (status) status.textContent = '界面加载失败，请刷新页面';
  console.error('Workbench initialization failed', error);
}
