import { applicationLifecycle as lifecycle } from './lifecycle.js';
import { map } from './map-controller.js';
import { catalogueItems, matchFor, matchSelection, mapSelection, persistState, renderSelected, renderCatalogue, showDetail, toggleMapFlight, focusFlight, switchMainTab, navigationState, datasetMaxPoints, pointFilterDraft, submitFlightFilters } from './flight-controller.js';
// Persistent workspace containers. React owns the flight table subtree.
const queryHost=document.createElement('section');queryHost.id='flight-query-host';
const flightSheet=document.createElement('section');flightSheet.id='flight-sheet';flightSheet.className='main-view hidden';
flightSheet.innerHTML='<header class="sheet-heading"><h2>航班</h2><span id="sheet-page-summary"></span></header><div id="flight-table-root" class="sheet-table-scroll"></div>';
flightSheet.querySelector('.sheet-heading').after(queryHost);
document.querySelector('.workspace').append(flightSheet);
const sheetPager=document.createElement('footer');sheetPager.className='sheet-pagination';sheetPager.append(document.querySelector('.flight-sidebar-footer'));flightSheet.append(sheetPager);
function renderFlightSheet(){
 document.querySelector('#sheet-page-summary').textContent=document.querySelector('#flight-page').textContent;
 window.dispatchEvent(new CustomEvent('flight-table-changed',{detail:{items:catalogueItems.map(item=>({...item,result:matchFor(item),selected:matchSelection.has(item.flight_key),onMap:mapSelection.has(item.flight_key)}))}}));
 if(typeof syncBatchControls==='function'&&typeof pageCheckbox!=='undefined')syncBatchControls();
}
window.workbenchFlights={
 snapshot:()=>catalogueItems.map(item=>({...item,result:matchFor(item),selected:matchSelection.has(item.flight_key),onMap:mapSelection.has(item.flight_key)})),
 select:(key,checked)=>{if(checked)matchSelection.add(key);else matchSelection.delete(key);persistState();renderSelected();renderCatalogue()},
 detail:key=>showDetail(key),
 toggleMap:key=>{const item=catalogueItems.find(item=>item.flight_key===key);if(item)toggleMapFlight(item)},
 focus:key=>focusFlight(key),
};
function openFlightSheet(){switchMainTab('flights')}
function navigateWorkspace(tab){
 navigationState.tab=tab;
 const split=document.body.classList.contains('flight-split-view');
 document.querySelector('#map-view').classList.toggle('hidden',tab!=='map'&&!split);
 document.querySelector('#observations-view').classList.toggle('hidden',tab!=='observations');
 flightSheet.classList.toggle('hidden',tab==='observations'||(!split&&tab!=='flights'));
 document.querySelector('#map-tab').classList.toggle('active',tab==='map');
 document.querySelector('#observations-tab').classList.toggle('active',tab!=='map');
 if(tab==='flights')renderFlightSheet();
 lifecycle.frame(()=>map.invalidateSize());
}
window.workbenchNavigation=navigateWorkspace;
document.querySelector('#observations-tab').textContent='航班';document.querySelector('#observations-tab').onclick=openFlightSheet;
const backToFlights=document.createElement('button');backToFlights.className='secondary-button';backToFlights.textContent='← 航班列表';backToFlights.onclick=openFlightSheet;document.querySelector('.observations-header').prepend(backToFlights);
const splitToggle=document.createElement('button');splitToggle.id='split-view-toggle';splitToggle.textContent='并排';splitToggle.title='地图与航班并排显示';splitToggle.setAttribute('aria-pressed','false');document.querySelector('.main-tabs').append(splitToggle);
let splitView=false;

function applySplitView(){
 if(!splitView)return;
 document.querySelector('#map-view').classList.remove('hidden');
 if(navigationState.tab!=='observations'){flightSheet.classList.remove('hidden');document.querySelector('#observations-view').classList.add('hidden')}
 document.querySelector('#map-tab').classList.toggle('active',navigationState.tab==='map');
 document.querySelector('#observations-tab').classList.toggle('active',navigationState.tab!=='map');
 lifecycle.frame(()=>map.invalidateSize());
}

document.querySelector('#observations-tab').onclick=openFlightSheet;backToFlights.onclick=openFlightSheet;
splitToggle.onclick=()=>{splitView=!splitView;document.body.classList.toggle('flight-split-view',splitView);splitToggle.setAttribute('aria-pressed',String(splitView));splitToggle.textContent=splitView?'单页':'并排';if(splitView){renderFlightSheet();if(navigationState.tab==='map')navigationState.tab='flights';applySplitView()}else switchMainTab(navigationState.tab==='observations'?'observations':navigationState.tab==='map'?'map':'flights');if(!splitView&&navigationState.tab==='flights')openFlightSheet()};
const splitGrip=document.createElement('div');splitGrip.className='workspace-split-grip';splitGrip.tabIndex=0;splitGrip.setAttribute('role','separator');splitGrip.setAttribute('aria-label','调整地图与航班比例');splitGrip.setAttribute('aria-orientation','vertical');document.querySelector('.workspace').append(splitGrip);
function setSplitRatio(x){const rect=document.querySelector('.workspace').getBoundingClientRect();const ratio=Math.max(25,Math.min(75,(x-rect.left)/rect.width*100));document.documentElement.style.setProperty('--map-split-width',ratio+'%');splitGrip.setAttribute('aria-valuenow',String(Math.round(ratio)));map.invalidateSize()}
splitGrip.onpointerdown=e=>{splitGrip.setPointerCapture(e.pointerId);e.preventDefault()};splitGrip.onpointermove=e=>{if(splitGrip.hasPointerCapture(e.pointerId))setSplitRatio(e.clientX)};splitGrip.onpointerup=e=>splitGrip.releasePointerCapture(e.pointerId);splitGrip.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const r=splitGrip.getBoundingClientRect();setSplitRatio(r.left+(e.key==='ArrowLeft'?-20:20))};


splitToggle.hidden=true;
const splitWorkspace=document.querySelector('.workspace');
const dropHint=document.createElement('div');dropHint.className='workspace-drop-hint';splitWorkspace.append(dropHint);
let draggedSheet=null;
for(const [id,sheet] of [['map-tab','map'],['observations-tab','flights']]){
 const tab=document.getElementById(id);tab.draggable=true;tab.title='拖到内容区左侧或右侧分屏';
 tab.addEventListener('dragstart',event=>{draggedSheet=sheet;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',sheet)});
 tab.addEventListener('dragend',()=>{draggedSheet=null;dropHint.classList.remove('visible')});
}
splitWorkspace.addEventListener('dragover',event=>{if(!draggedSheet||event.target.closest('.main-tabs'))return;event.preventDefault();event.dataTransfer.dropEffect='move';const rect=splitWorkspace.getBoundingClientRect();const left=event.clientX<rect.left+rect.width/2;dropHint.classList.add('visible');dropHint.classList.toggle('drop-left',left);dropHint.textContent=left?'在左侧打开':'在右侧打开'});
splitWorkspace.addEventListener('drop',event=>{if(!draggedSheet||event.target.closest('.main-tabs'))return;event.preventDefault();const rect=splitWorkspace.getBoundingClientRect(),left=event.clientX<rect.left+rect.width/2;document.body.classList.toggle('flight-map-right',draggedSheet==='map'?!left:left);if(!splitView)splitToggle.click();applySplitView();dropHint.classList.remove('visible');draggedSheet=null});
splitWorkspace.addEventListener('dragleave',event=>{if(!splitWorkspace.contains(event.relatedTarget))dropHint.classList.remove('visible')});
document.querySelector('.main-tabs').addEventListener('dragover',event=>{if(draggedSheet){event.preventDefault();event.stopPropagation();dropHint.classList.remove('visible')}});
document.querySelector('.main-tabs').addEventListener('drop',event=>{if(!draggedSheet)return;event.preventDefault();event.stopPropagation();const sheet=draggedSheet;if(splitView)splitToggle.click();document.body.classList.remove('flight-map-right');if(sheet==='map')switchMainTab('map');else openFlightSheet();draggedSheet=null;dropHint.classList.remove('visible')});


const batchTools=document.createElement('div');batchTools.className='sheet-batch-tools';
const selectPage=document.querySelector('#select-page'),selectAll=document.querySelector('#select-filtered'),clearSelectionButton=document.querySelector('#clear-match-selection');
const pageCheckbox=document.createElement('input');pageCheckbox.type='checkbox';pageCheckbox.setAttribute('aria-label','选择本页航班');
pageCheckbox.onchange=()=>{catalogueItems.forEach(item=>{if(pageCheckbox.checked)matchSelection.add(item.flight_key);else matchSelection.delete(item.flight_key)});persistState();renderSelected();renderCatalogue()};
const pageLabel=document.createElement('label');pageLabel.append(pageCheckbox,document.createTextNode('本页'));batchTools.append(pageLabel,selectAll,clearSelectionButton);selectPage.hidden=true;
const selectedCount=document.createElement('span');selectedCount.className='sheet-selected-count';batchTools.append(selectedCount);flightSheet.querySelector('.sheet-heading').append(batchTools);
function syncBatchControls(){const count=catalogueItems.filter(item=>matchSelection.has(item.flight_key)).length;pageCheckbox.checked=catalogueItems.length>0&&count===catalogueItems.length;pageCheckbox.indeterminate=count>0&&count<catalogueItems.length;selectedCount.textContent=matchSelection.size?'已选 '+matchSelection.size+' 条':'';clearSelectionButton.hidden=matchSelection.size===0;}
lifecycle.listen(window,'flight-selection-changed',syncBatchControls);
selectAll.textContent='选择全部结果';clearSelectionButton.textContent='清空';
const resetFilters=document.createElement('button');resetFilters.className='filter-reset';resetFilters.textContent='重置';document.querySelector('.flight-sidebar-header').append(resetFilters);


renderFlightSheet();

// Filter edits remain a draft until explicitly submitted.
for(const id of ['flight-search','flight-movement','flight-status','flight-min-points','flight-max-points']){const element=document.getElementById(id);element.onchange=null;element.onkeydown=null;}
resetFilters.onclick=()=>{document.querySelector('#flight-search').value='';document.querySelector('#flight-movement').value='';document.querySelector('#flight-status').value='';document.querySelector('#flight-min-points').value=0;document.querySelector('#flight-max-points').value=datasetMaxPoints;pointFilterDraft.edit()};

lifecycle.listen(window,'submit-flight-filters',submitFlightFilters);

lifecycle.listen(window,'flight-catalogue-changed',renderFlightSheet);

lifecycle.own(()=>{delete window.workbenchFlights;delete window.workbenchNavigation;});
