import { applicationLifecycle } from './controllers/lifecycle.js';
import 'leaflet/dist/leaflet.css';
import './styles/tokens.css';
import './styles/workbench.css';

try {
  const { initialState } = await import('./controllers/map-controller.js');
  const state = await initialState;
  if (state?.flight_mode) {
    document.querySelector('.main-tabs')?.classList.remove('hidden');
    await import('./controllers/flight-controller.js');
    await import('./controllers/workspace-controller.js');
  } else {
    for (const selector of ['.main-tabs', '#flights-panel', '#observations-view']) {
      document.querySelector(selector)?.remove();
    }
  }
  await import('./shell.js');
  if (state?.flight_mode) {
    const { mountFlightTable } = await import('./features/flights/FlightTable');
    applicationLifecycle.own(mountFlightTable());
  }
} catch (error) {
  const status = document.getElementById('status');
  if (status) status.textContent = '界面加载失败，请刷新页面';
  console.error('Workbench initialization failed', error);
}

window.addEventListener("pagehide", (event) => { if (!event.persisted) applicationLifecycle.dispose(); }, { once: true });
