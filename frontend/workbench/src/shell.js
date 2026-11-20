import { applicationLifecycle as lifecycle } from './controllers/lifecycle.js';
import { MapToolbar, initializeMapState, useMapState } from './features/map/MapToolbar';
import React from 'react';
import {createRoot} from 'react-dom/client';
import {ConfigProvider,Button,Space,Menu} from 'antd';
const iconPaths={
'search-toggle':['M21 21l-5-5','M19 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0'],
 'topology-toggle':['M8 6h8M6 8v8m12-8v8M8 18h8','M3 3h5v5H3zM16 3h5v5h-5zM3 16h5v5H3zM16 16h5v5h-5z'],
 left:['M3 4h18v16H3z','M9 4v16'],right:['M3 4h18v16H3z','M15 4v16']};
function studioIcon(name){return React.createElement('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.5,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true},...(iconPaths[name]||[]).map((d,i)=>React.createElement('path',{key:i,d})));}
const flightMode = document.body.classList.contains('flight-mode');
lifecycle.own(initializeMapState());
function mountOwned(element,content){const root=createRoot(element);root.render(content);lifecycle.own(()=>root.unmount());}
const h=React.createElement, old=document.querySelector('.top-actions');
const root=document.createElement('div');root.className='react-actions';old.before(root);
const nav=document.createElement('div');document.querySelector('.dock-title').after(nav);
const mapToolsRoot=document.createElement('div');mapToolsRoot.className='map-tools';document.querySelector('#map-view').append(mapToolsRoot);const mapToolsMount=document.createElement('div');mapToolsRoot.append(mapToolsMount);mountOwned(mapToolsMount,h(MapToolbar,{mapTools:true}));
mountOwned(root,h(MapToolbar));
if (!flightMode) mountOwned(nav,h(MapToolbar,{dock:true}));
// Keep legacy actions available if the module fails to load.
document.body.classList.add('react-ready');



const inspector=document.createElement('aside');inspector.className='studio-inspector';document.querySelector('.workspace').after(inspector);
function Inspector(){React.useLayoutEffect(()=>{movePanels();if(flightMode)organizeFlightPanels()},[]);const state=useMapState();const counts=`${state.nodeCount} 节点 · ${state.edgeCount} 边${flightMode ? ` · ${state.flightCount} 航班` : ""}`;return h(ConfigProvider,{theme:{token:{colorPrimary:'#2563eb',borderRadius:4,fontSize:13}}},h('div',{className:'inspector-inner'},h('h1',null,'机场地面网络'),h('div',{className:'studio-metrics'},counts.split(' · ').map((c,i)=>h('div',{key:i},h('strong',null,c.split(' ')[0]),h('span',null,c.split(' ').slice(1).join(' '))))),h('section',null,h('h3',null,'图层与底图'),h('div',{id:'studio-layers'})),h('section',null,h('h3',null,'地图图例'),h('div',{id:'studio-legend'})),h('section',{className:'inspector-empty'},h('div',{className:'selection-symbol'},'⌖'),h('h3',null,'选择一个图要素'),null)))}
mountOwned(inspector,h(Inspector));
const movePanels=()=>{const a=document.querySelector('#studio-layers'),b=document.querySelector('#studio-legend');if(!a||!b)throw new Error('Inspector slots are not mounted');a.append(document.querySelector('#layer-control-slot'));b.append(document.querySelector('.legend'));};
// Shared rail sizing: pointer + keyboard, persisted per browser.
const sizingRoot=document.documentElement;
const sizingStyle=getComputedStyle(sizingRoot);
const minimumRail=parseFloat(sizingStyle.getPropertyValue('--sidebar-min-width'));
const maximumRail=parseFloat(sizingStyle.getPropertyValue('--sidebar-max-width'));
function setRailWidth(value){
 const visibleRails=railHandles.filter(item=>!item.handle.hidden).length||2;
 const available=Math.max(minimumRail,Math.min(maximumRail,(innerWidth-320)/visibleRails));
 const width=Math.round(Math.max(minimumRail,Math.min(available,value)));
 sizingRoot.style.setProperty('--sidebar-width',width+'px');
 try{localStorage.setItem('airport-workbench.sidebar-width',String(width))}catch{}
 window.dispatchEvent(new Event('resize'));
}
const railHandles=['left','right'].map(side=>{
 const handle=document.createElement('button');handle.className='sidebar-resizer';handle.hidden=true;
 handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');
 handle.setAttribute('aria-label',side==='left'?'调整左侧栏宽度':'调整右侧栏宽度');
 handle.title='拖动调整侧栏宽度 · 方向键微调 · 双击恢复';document.body.append(handle);
 const item={side,handle};
 handle.addEventListener('pointerdown',event=>{event.preventDefault();handle.setPointerCapture(event.pointerId);item.startX=event.clientX;item.startWidth=parseFloat(getComputedStyle(sizingRoot).getPropertyValue('--sidebar-width'));document.body.classList.add('sidebar-resizing')});
 handle.addEventListener('pointermove',event=>{if(handle.hasPointerCapture(event.pointerId))setRailWidth(item.startWidth+(event.clientX-item.startX)*(side==='left'?1:-1))});
 const stop=()=>{document.body.classList.remove('sidebar-resizing')};
 handle.addEventListener('pointerup',event=>{if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);stop()});handle.addEventListener('lostpointercapture',stop);
 handle.addEventListener('dblclick',()=>setRailWidth(304));
 handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home'].includes(event.key))return;event.preventDefault();const width=parseFloat(getComputedStyle(sizingRoot).getPropertyValue('--sidebar-width'));setRailWidth(event.key==='Home'?304:width+(event.key==='ArrowRight'?1:-1)*(side==='left'?1:-1)*(event.shiftKey?32:8))});
 return item;
});
function placeRailHandles(){
 const mapRect=document.querySelector('.workspace').getBoundingClientRect();
 railHandles.forEach(({side,handle})=>{
 const boundary=side==='left'?mapRect.left:mapRect.right;
 handle.hidden=innerWidth<=680||(side==='left'?boundary<10:innerWidth-boundary<10);
 handle.style.left=(boundary-5)+'px';handle.style.top=mapRect.top+'px';handle.style.height=mapRect.height+'px';
 handle.setAttribute('aria-valuemin',String(minimumRail));handle.setAttribute('aria-valuemax',String(maximumRail));handle.setAttribute('aria-valuenow',String(parseFloat(getComputedStyle(sizingRoot).getPropertyValue('--sidebar-width'))));
 });
}
lifecycle.observe(document.querySelector('.workspace'),placeRailHandles);
lifecycle.listen(window,'resize',placeRailHandles);
try{const stored=Number(localStorage.getItem('airport-workbench.sidebar-width'));if(stored>=minimumRail&&stored<=maximumRail)sizingRoot.style.setProperty('--sidebar-width',stored+'px')}catch{}
placeRailHandles();

// Flight catalogue stays on the left; selection and matching live in the inspector.

function organizeFlightPanels(){


 if(!document.querySelector('#flight-selection-inspector')){
 const section=document.createElement('section');section.id='flight-selection-inspector';
 const heading=document.createElement('h3');heading.textContent='航班选择';section.append(heading);
 document.querySelector('#flight-query-host').append(section);
 ['.match-selection','#match-progress'].forEach(selector=>{const item=document.querySelector(selector);if(item)section.append(item)});
 const footer=document.querySelector('.footer-actions');if(footer)section.append(footer);document.querySelector('#flight-list-view').append(document.querySelector('.map-selection'));
 document.querySelector('.flight-sidebar-header h2').textContent='地图展示';
 document.querySelector('#flight-search').placeholder='搜索航班号 / ID';
 document.querySelectorAll('.match-selection .field-note,.section-title>span').forEach(item=>item.hidden=true);
 }

}


function compactFlightControls(){
 const labels={'select-page':'本页','select-filtered':'全部结果','clear-match-selection':'清空','clear-map-selection':'清空','fit-selected':'定位','reset-point-filter':'重置'};
 Object.entries(labels).forEach(([id,text])=>document.getElementById(id).textContent=text);
 document.querySelector('#flight-search').placeholder='航班号 / ID';
 document.querySelector('#flight-movement option[value=""]').textContent='进出港';document.querySelector('#flight-status option[value=""]').textContent='匹配状态';
 document.querySelector('.point-filter>span').textContent='点数';
 document.querySelector('#flight-min-points').setAttribute('aria-label','最小观测点数');
}
if(flightMode)compactFlightControls();

const headerBar=document.querySelector('.topbar');
function addRailToggle(side){
 const button=document.createElement('button');button.className='rail-toggle rail-toggle-'+side;
 const label=side==='left'?'左侧栏':'右侧栏';button.title='隐藏'+label;button.setAttribute('aria-label','切换'+label);button.setAttribute('aria-expanded','true');
 const mount=document.createElement('span');button.append(mount);mountOwned(mount,studioIcon(side));
 if(side==='left')headerBar.prepend(button);else headerBar.append(button);
 button.onclick=()=>{const hidden=document.body.classList.toggle('hide-'+side+'-rail');button.title=(hidden?'显示':'隐藏')+label;button.setAttribute('aria-expanded',String(!hidden));window.dispatchEvent(new Event('resize'))};
}
addRailToggle('left');addRailToggle('right');

for(const selector of ['#search-panel','#topology-panel'])document.querySelector('#map-view').append(document.querySelector(selector));

if (flightMode) {
 const queryHost=document.querySelector('#flight-query-host');queryHost.prepend(document.querySelector('.flight-query'));
 const resetButton=document.querySelector('.filter-reset');if(resetButton)queryHost.prepend(resetButton);
 document.querySelector('.flight-sidebar-header h2').textContent='地图展示';

 const filterButton=document.createElement('button');filterButton.className='secondary-button flight-filter-submit';filterButton.textContent='过滤';filterButton.onclick=()=>window.dispatchEvent(new Event('submit-flight-filters'));
 const filterActions=document.querySelector('#match-selected').parentElement;filterActions.prepend(filterButton);if(resetButton)filterActions.append(resetButton);

}

// A single rail owns layout, resizing and visibility; only its content changes.
const leftRail=document.createElement('aside');leftRail.id='left-rail';leftRail.setAttribute('aria-label','左侧栏');
const editorTools=document.querySelector('.tool-dock');editorTools.replaceWith(leftRail);
leftRail.append(flightMode ? document.querySelector('#flights-panel') : editorTools);

lifecycle.own(()=>{railHandles.forEach(({handle})=>handle.remove());document.body.classList.remove("sidebar-resizing");});

if(flightMode){
 const bulkMapButton=document.createElement('button');
 bulkMapButton.id='add-selected-to-map';
 bulkMapButton.disabled=document.querySelector('#match-selected').disabled;
 bulkMapButton.className='secondary-button';
 bulkMapButton.textContent='所选加入地图';
 bulkMapButton.onclick=()=>window.dispatchEvent(new Event('add-selected-to-map'));
 document.querySelector('#match-selected')?.after(bulkMapButton);
}
