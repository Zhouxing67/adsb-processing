// Flight sheet, selection toolbar, and drag-to-split workspace.
const flightSheet=document.createElement('section');flightSheet.id='flight-sheet';flightSheet.className='main-view hidden';document.querySelector('.workspace').append(flightSheet);
const baseCatalogue=renderCatalogue;
renderCatalogue=function(){baseCatalogue();renderFlightSheet()};
function renderFlightSheet(){
 flightSheet.innerHTML=`<header class="sheet-heading"><h2>航班</h2><span>${document.querySelector('#flight-page').textContent}</span></header><div class="sheet-table-scroll"><table class="sheet-table"><thead><tr><th>选择</th><th>航班</th><th>进出港</th><th>状态</th><th>观测点</th><th>开始时间 <small>UTC</small></th><th>操作</th></tr></thead><tbody>${catalogueItems.map(item=>{const key=item.flight_key,result=matchFor(item);return `<tr data-key="${escapeHtml(key)}"><td><input type="checkbox" aria-label="选择航班 ${escapeHtml(item.flight_id)}" ${matchSelection.has(key)?'checked':''}></td><td><strong>${escapeHtml(item.flight_number||item.flight_id)}</strong><small>${escapeHtml(item.flight_id)}</small></td><td>${item.movement_type==='arrival'?'进港':item.movement_type==='departure'?'离港':'未知'}</td><td><span class="flight-status ${result.status}">${STATUS_LABELS[result.status]}</span></td><td>${item.point_count}</td><td>${escapeHtml(item.start_time?.replace('T',' ').replace(/\+00:00$/,''))}</td><td><button class="sheet-detail secondary-button">详情</button><button class="sheet-map secondary-button">${mapSelection.has(key)?'移出地图':'加入地图'}</button><button class="sheet-focus secondary-button" ${mapSelection.has(key)?'':'disabled'}>定位</button></td></tr>`}).join('')}</tbody></table></div>`;
 flightSheet.querySelectorAll('tbody tr').forEach(row=>{const item=catalogueItems.find(x=>x.flight_key===row.dataset.key);row.querySelector('input').onchange=e=>{if(e.target.checked)matchSelection.add(item.flight_key);else matchSelection.delete(item.flight_key);persistState();renderSelected();baseCatalogue()};row.querySelector('.sheet-detail').onclick=()=>showDetail(item.flight_key);row.querySelector('.sheet-map').onclick=()=>toggleMapFlight(item);row.querySelector('.sheet-focus').onclick=()=>{switchMainTab('map');focusFlight(item.flight_key)}});
}
const originalSwitchTab=switchMainTab;
switchMainTab=function(tab){originalSwitchTab(tab);flightSheet.classList.add('hidden');document.querySelector('#observations-tab').classList.toggle('active',tab!=='map')};
function openFlightSheet(){originalSwitchTab('flights');flightSheet.classList.remove('hidden');document.querySelector('#observations-tab').classList.add('active');renderFlightSheet()}
document.querySelector('#observations-tab').textContent='航班';document.querySelector('#observations-tab').onclick=openFlightSheet;
const backToFlights=document.createElement('button');backToFlights.className='secondary-button';backToFlights.textContent='← 航班列表';backToFlights.onclick=openFlightSheet;document.querySelector('.observations-header').prepend(backToFlights);
const originalFocus=focusFlight;focusFlight=function(key){switchMainTab('map');originalFocus(key)};
renderFlightSheet();
const sheetPager=document.createElement('footer');sheetPager.className='sheet-pagination';
sheetPager.append(document.querySelector('.flight-sidebar-footer'));
flightSheet.append(sheetPager);
// Keep the existing pager (and its handlers) across table refreshes.
const renderSheetWithPager=renderFlightSheet;
renderFlightSheet=function(){
 const pager=document.querySelector('.sheet-pagination');
 if(pager){pager.hidden=true;document.body.append(pager);}
 renderSheetWithPager();
 if(pager){flightSheet.append(pager);pager.hidden=false;}
};


const splitToggle=document.createElement('button');splitToggle.id='split-view-toggle';splitToggle.textContent='并排';splitToggle.title='地图与航班并排显示';splitToggle.setAttribute('aria-pressed','false');document.querySelector('.main-tabs').append(splitToggle);
let splitView=false;
const switchBeforeSplit=switchMainTab;
function applySplitView(){
 if(!splitView)return;
 document.querySelector('#map-view').classList.remove('hidden');
 if(currentMainTab!=='observations'){flightSheet.classList.remove('hidden');document.querySelector('#observations-view').classList.add('hidden')}
 document.querySelector('#map-tab').classList.toggle('active',currentMainTab==='map');
 document.querySelector('#observations-tab').classList.toggle('active',currentMainTab!=='map');
 requestAnimationFrame(()=>map.invalidateSize());
}
switchMainTab=function(tab){switchBeforeSplit(tab);applySplitView()};
const openBeforeSplit=openFlightSheet;openFlightSheet=function(){openBeforeSplit();applySplitView()};document.querySelector('#observations-tab').onclick=openFlightSheet;backToFlights.onclick=openFlightSheet;
splitToggle.onclick=()=>{splitView=!splitView;document.body.classList.toggle('flight-split-view',splitView);splitToggle.setAttribute('aria-pressed',String(splitView));splitToggle.textContent=splitView?'单页':'并排';if(splitView){renderFlightSheet();if(currentMainTab==='map')currentMainTab='flights';applySplitView()}else switchMainTab(currentMainTab==='observations'?'observations':currentMainTab==='map'?'map':'flights');if(!splitView&&currentMainTab==='flights')openFlightSheet()};
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
const selectedCount=document.createElement('span');selectedCount.className='sheet-selected-count';batchTools.append(selectedCount);
const previousSheetRender=renderFlightSheet;
renderFlightSheet=function(){document.body.append(batchTools);batchTools.hidden=true;previousSheetRender();document.querySelector('.sheet-heading').after(batchTools);batchTools.hidden=false;syncBatchControls()};
function syncBatchControls(){const count=catalogueItems.filter(item=>matchSelection.has(item.flight_key)).length;pageCheckbox.checked=catalogueItems.length>0&&count===catalogueItems.length;pageCheckbox.indeterminate=count>0&&count<catalogueItems.length;selectedCount.textContent=matchSelection.size?'已选 '+matchSelection.size+' 条':'';clearSelectionButton.hidden=matchSelection.size===0;}
const previousSelectedRender=renderSelected;renderSelected=function(){previousSelectedRender();syncBatchControls()};
selectAll.textContent='选择全部结果';clearSelectionButton.textContent='清空';
const resetFilters=document.createElement('button');resetFilters.className='filter-reset';resetFilters.textContent='重置';document.querySelector('.flight-sidebar-header').append(resetFilters);
resetFilters.onclick=()=>{activeSearch='';document.querySelector('#flight-search').value='';document.querySelector('#flight-movement').value='';document.querySelector('#flight-status').value='';resetPointFilter()};
['#flight-min-points','#flight-max-points'].forEach(selector=>{document.querySelector(selector).addEventListener('change',()=>applyPointFilter())});
document.querySelector('#flight-search').addEventListener('change',event=>{activeSearch=event.target.value.trim();queryCatalogue(1)});
renderFlightSheet();
