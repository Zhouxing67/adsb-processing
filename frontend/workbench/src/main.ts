import { applicationLifecycle } from './controllers/lifecycle.js';
import 'leaflet/dist/leaflet.css';
import './styles/tokens.css';
import './styles/workbench.css';

try {
  await import('./controllers/map-controller.js');
  await import('./controllers/flight-controller.js');
  await import('./controllers/workspace-controller.js');
  await import('./shell.js');
  const { mountFlightTable } = await import('./features/flights/FlightTable');
  applicationLifecycle.own(mountFlightTable());
} catch (error) {
  const status = document.getElementById('status');
  if (status) status.textContent = '界面加载失败，请刷新页面';
  console.error('Workbench initialization failed', error);
}

window.addEventListener("pagehide", (event) => { if (!event.persisted) applicationLifecycle.dispose(); }, { once: true });
