import React from 'react';
import {createRoot} from 'react-dom/client';
import {ConfigProvider,Button,Space,Menu} from 'antd';
const iconPaths={
'search-toggle':['M21 21l-5-5','M19 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0'],
 'topology-toggle':['M8 6h8M6 8v8m12-8v8M8 18h8','M3 3h5v5H3zM16 3h5v5h-5zM3 16h5v5H3zM16 16h5v5h-5z'],
 left:['M3 4h18v16H3z','M9 4v16'],right:['M3 4h18v16H3z','M15 4v16']};
function studioIcon(name){return React.createElement('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.5,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true},...(iconPaths[name]||[]).map((d,i)=>React.createElement('path',{key:i,d})));}
const h=React.createElement, old=document.querySelector('.top-actions'), tools=[...document.querySelectorAll('.tool')];
const actions=[...old.querySelectorAll('button')];
const root=document.createElement('div');root.className='react-actions';old.before(root);
const nav=document.createElement('div');document.querySelector('.dock-title').after(nav);
function UI({dock=false}){const [n,set]=React.useState(0);React.useEffect(()=>{const o=new MutationObserver(()=>set(x=>x+1));o.observe(old,{subtree:true,attributes:true});o.observe(document.body,{attributes:true,attributeFilter:['class']});tools.forEach(t=>o.observe(t,{attributes:true}));return()=>o.disconnect()},[]);return h(ConfigProvider,{theme:{token:{colorPrimary:'#2563eb',borderRadius:5,fontSize:13,fontFamily:'Segoe UI, Microsoft YaHei, sans-serif'}}},dock?h(Menu,{selectedKeys:[tools.find(t=>t.classList.contains('active'))?.dataset.mode],items:tools.flatMap((t,i)=>[...(i===1||i===4||i===6?[{type:'divider',key:'divider-'+i}]:[]),{key:t.dataset.mode,label:t.querySelector('em').textContent,danger:t.dataset.mode==='delete',icon:h('span',{className:'studio-tool-icon','aria-hidden':true},({inspect:'⌖',split:'⊥',draw:'＋',restore:'⌁',merge:'⋈',snap:'↦',delete:'−'})[t.dataset.mode])}]),onClick:({key})=>tools.find(t=>t.dataset.mode===key).click()}):h(Space,{size:4},actions.filter(a=>!a.classList.contains('hidden') && getComputedStyle(a).display!=='none').map(a=>h(Button,{key:a.id,type:['save','finish'].includes(a.id)?'primary':'text',disabled:a.disabled,title:iconPaths[a.id]?(a.id==='search-toggle'?'搜索':'拓扑检查'):undefined,'aria-label':iconPaths[a.id]?(a.id==='search-toggle'?'搜索':'拓扑检查'):undefined,className:iconPaths[a.id]?'studio-icon-button':'',onClick:()=>a.click()},iconPaths[a.id]?studioIcon(a.id):a.textContent.replace(/^[^\u4e00-\u9fff]+/,'').trim()))))}
createRoot(root).render(h(UI));createRoot(nav).render(h(UI,{dock:true}));
// Keep legacy actions available if the module fails to load.
document.body.classList.add('react-ready');



const inspector=document.createElement('aside');inspector.className='studio-inspector';document.querySelector('.workspace').after(inspector);
function Inspector(){const [counts,setCounts]=React.useState(document.querySelector('#counts').textContent);React.useEffect(()=>{const o=new MutationObserver(()=>setCounts(document.querySelector('#counts').textContent));o.observe(document.querySelector('#counts'),{childList:true,characterData:true,subtree:true});return()=>o.disconnect()},[]);return h(ConfigProvider,{theme:{token:{colorPrimary:'#2563eb',borderRadius:4,fontSize:13}}},h('div',{className:'inspector-inner'},h('h1',null,'机场地面网络'),h('div',{className:'studio-metrics'},counts.split(' · ').map((c,i)=>h('div',{key:i},h('strong',null,c.split(' ')[0]),h('span',null,c.split(' ').slice(1).join(' '))))),h('section',null,h('h3',null,'图层与底图'),h('div',{id:'studio-layers'})),h('section',null,h('h3',null,'地图图例'),h('div',{id:'studio-legend'})),h('section',{className:'inspector-empty'},h('div',{className:'selection-symbol'},'⌖'),h('h3',null,'选择一个图要素'),null)))}
createRoot(inspector).render(h(Inspector));
const movePanels=()=>{const a=document.querySelector('#studio-layers'),b=document.querySelector('#studio-legend');if(!a||!b){requestAnimationFrame(movePanels);return}a.append(document.querySelector('#layer-control-slot'));b.append(document.querySelector('.legend'));};movePanels();
// A restrained base makes the airport geometry legible before users add context.
let initialized=false;
const simplifyMap=()=>{if(initialized)return;const inputs=[...document.querySelectorAll('.leaflet-control-layers-base label')];const blank=inputs.find(x=>x.textContent.includes('无底图'));const nodes=[...document.querySelectorAll('.leaflet-control-layers-overlays label')].find(x=>x.textContent.includes('图节点'));if(blank&&nodes){blank.querySelector('input').click();if(nodes.querySelector('input').checked)nodes.querySelector('input').click();initialized=true;observer.disconnect();}};
const observer=new MutationObserver(simplifyMap);observer.observe(document.querySelector('#layer-control-slot'),{childList:true,subtree:true});simplifyMap();

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
const railObserver=new ResizeObserver(placeRailHandles);railObserver.observe(document.querySelector('.workspace'));
window.addEventListener('resize',placeRailHandles);
try{const stored=Number(localStorage.getItem('airport-workbench.sidebar-width'));if(stored>=minimumRail&&stored<=maximumRail)sizingRoot.style.setProperty('--sidebar-width',stored+'px')}catch{}
placeRailHandles();

// Flight catalogue stays on the left; selection and matching live in the inspector.
const flightLayoutObserver=new MutationObserver(organizeFlightPanels);
function organizeFlightPanels(){
 if(!document.body.classList.contains('flight-mode'))return;
 const inner=document.querySelector('.inspector-inner');if(!inner)return;
 if(!document.querySelector('#flight-selection-inspector')){
 const section=document.createElement('section');section.id='flight-selection-inspector';
 const heading=document.createElement('h3');heading.textContent='航班选择';section.append(heading);
 document.querySelector('.flight-query').after(section);
 ['.match-selection','.map-selection','#match-progress'].forEach(selector=>{const item=document.querySelector(selector);if(item)section.append(item)});
 const footer=document.querySelector('.footer-actions');if(footer)section.append(footer);
 document.querySelector('.flight-sidebar-header h2').textContent='航班目录';
 document.querySelector('#flight-search').placeholder='搜索航班号 / ID';
 document.querySelectorAll('.match-selection .field-note,.section-title>span').forEach(item=>item.hidden=true);
 }
 flightLayoutObserver.disconnect();
}
flightLayoutObserver.observe(document.body,{attributes:true,attributeFilter:['class']});organizeFlightPanels();

function compactFlightControls(){
 const labels={'select-page':'本页','select-filtered':'全部结果','clear-match-selection':'清空','clear-map-selection':'清空','fit-selected':'定位','reset-point-filter':'重置'};
 Object.entries(labels).forEach(([id,text])=>document.getElementById(id).textContent=text);
 document.querySelector('#flight-search').placeholder='航班号 / ID';
 document.querySelector('#flight-movement option[value=""]').textContent='进出港';document.querySelector('#flight-status option[value=""]').textContent='匹配状态';
 document.querySelector('.point-filter>span').textContent='点数';
 document.querySelector('#flight-min-points').setAttribute('aria-label','最小观测点数');
}
compactFlightControls();

const headerBar=document.querySelector('.topbar');
function addRailToggle(side){
 const button=document.createElement('button');button.className='rail-toggle rail-toggle-'+side;
 const label=side==='left'?'左侧栏':'右侧栏';button.title='隐藏'+label;button.setAttribute('aria-label','切换'+label);button.setAttribute('aria-expanded','true');
 const mount=document.createElement('span');button.append(mount);createRoot(mount).render(studioIcon(side));
 if(side==='left')headerBar.prepend(button);else headerBar.append(button);
 button.onclick=()=>{const hidden=document.body.classList.toggle('hide-'+side+'-rail');button.title=(hidden?'显示':'隐藏')+label;button.setAttribute('aria-expanded',String(!hidden));window.dispatchEvent(new Event('resize'))};
}
addRailToggle('left');addRailToggle('right');
