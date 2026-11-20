import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import './styles/tokens.css';
import { App } from './app/App';

const root = document.getElementById('root');
if (!root) throw new Error('React root is missing');

createRoot(root).render(<StrictMode><App /></StrictMode>);
