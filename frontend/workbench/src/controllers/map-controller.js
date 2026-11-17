import { popupPosition } from '../domain/popup-layout';
import { propertyPatch, requireRevision } from '../domain/properties';
import { applicationLifecycle as lifecycle } from './lifecycle.js';
import L from 'leaflet';
const map = L.map("map", {preferCanvas: false, zoomControl: false, maxZoom: 26});
map.createPane("edgeCasingPane"); map.getPane("edgeCasingPane").style.zIndex = 410;
map.createPane("edgesPane"); map.getPane("edgesPane").style.zIndex = 420;
map.createPane("flightPane"); map.getPane("flightPane").style.zIndex = 510;
map.createPane("pathPane"); map.getPane("pathPane").style.zIndex = 530;
map.createPane("selectionEdgePane"); map.getPane("selectionEdgePane").style.zIndex = 610;
map.createPane("nodesPane"); map.getPane("nodesPane").style.zIndex = 650;
map.createPane("previewPane"); map.getPane("previewPane").style.zIndex = 660;
map.createPane("selectionPane"); map.getPane("selectionPane").style.zIndex = 670;

const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap contributors",maxNativeZoom:19,maxZoom:26});
const satellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {attribution: "Esri, Maxar, Earthstar Geographics",maxNativeZoom:19,maxZoom:26});
const blankBase = L.layerGroup().addTo(map);
const layers = L.control.layers({"OpenStreetMap": osm, "ESRI 卫星": satellite, "无底图（精细编辑）": blankBase}, {}, {collapsed: false, position: "topleft"}).addTo(map);
document.querySelector("#layer-control-slot").appendChild(layers.getContainer());

let mode = "inspect", nodeLayer, edgeLayer, edgeGroup, previewLayer, endpointLayer, selectionLayer;
let splitValidation = false, currentState = null;
let dataLayers = [];
let nodeFeatures = [], fitted = false, savePath = "", firstNode = null;
let mergeNodeIds = [];
let firstNodeRevision = null, mergeSelectionRevision = null;
let nodeReviewSnapshot = [], nodeReviewIndex = -1, lastTopologyRevision = null, selectedNodeKey = null;
let activeOperationRevision = null;
let narrowDetailsReturnToTopology = false;
let topologyInspectionActive = false, topologyPreviousNodeVisibility = false, topologyPreviousEdgeVisibility = true;
function identityKey(value){return JSON.stringify(value);}
function nodeKey(value){return identityKey(value?.properties?.id??value);}
function edgeKey(value){return identityKey(value?.properties?.id??value);}
function sortedNodeReviewSnapshot(features){return [...features].sort((a,b)=>nodeKey(a).localeCompare(nodeKey(b)));}
const nodeFeatureIndex = new Map(), nodeSearchIndex = new Map(), edgeSearchIndex = new Map(), edgeIdentityIndex = new Map();
const status = document.querySelector("#status"), busy = document.querySelector("#busy");
const details = document.querySelector("#details"), detailsContent = document.querySelector("#details-content");
const topologyPanel = document.querySelector("#topology-panel"), topologyBack = document.querySelector("#back-to-topology");
const messages = {
  inspect: "查看模式 · 点击节点或派生边查看来源信息",
  split: "补充分割点 · 点击派生边上的正确位置；优先复用附近的原始 OSM Node",
  draw: "直接绘制连接 · 选择起点，点击地图添加形状点，再选择终点",
  restore: "恢复来源连接 · 依次点击两个图节点，从原始 SourceEdge 网络恢复曲线",
  merge: "合并节点 · 从候选列表选择，或连续点击节点后停止选择",
  snap: "人工吸附到边 · 先选误差节点，再选它本应接入的派生边",
  delete: "删除 / 简化 · 删除边只改拓扑；删除节点可人工选择半边重组"
};

let conflictNotice=false;
function setStatus(message) { if(!conflictNotice)status.textContent = message;publishMapState(); }
function escapeHtml(value) { return String(value ?? "—").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]); }
function normalizeId(value) { return String(value ?? "").trim().replace(/^['"]|['"]$/g, ""); }
function edgePairKey(u, v) { return [normalizeId(u), normalizeId(v)].sort().join("|"); }
async function readResponse(response) { const text = await response.text(); let value; try { value = text ? JSON.parse(text) : {}; } catch { value = {detail:text}; } if (!response.ok){const detail=value.detail||value.message||`HTTP ${response.status}`;const error=new Error(typeof detail==="object"?detail.message:detail);error.code=typeof detail==="object"?detail.code:null;throw error;} return value; }
async function post(path, body, reload = false) {
  busy.classList.remove("hidden");
  try { const value = await readResponse(await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)})); if (reload) await loadState(); return value; }
  catch(error){if(error.code==="revision_conflict"){closeDetails();firstNode=null;firstNodeRevision=null;mergeNodeIds=[];mergeSelectionRevision=null;conflictNotice=true;status.textContent="图已变更，请重新检查操作";try{await loadState();}catch{}throw error;}throw error;}
  finally { busy.classList.add("hidden"); }
}
function clearPreview() { if (previewLayer) { map.removeLayer(previewLayer); previewLayer = null; } }
function clearEndpointHighlight() { if (endpointLayer) { map.removeLayer(endpointLayer); endpointLayer = null; } }
function clearSelection() { if (selectionLayer) { map.removeLayer(selectionLayer); selectionLayer = null; } }
function refreshMapLayout(){lifecycle.frame(()=>map.invalidateSize());}
function isNarrowLayout(){return window.matchMedia("(max-width: 1050px)").matches;}
function shouldSwapTopologyPanel(){return Boolean(currentState?.flight_mode)||isNarrowLayout();}
function setTopologyInspection(active){if(active===topologyInspectionActive)return;if(active){topologyPreviousNodeVisibility=Boolean(nodeLayer&&map.hasLayer(nodeLayer));topologyPreviousEdgeVisibility=Boolean(edgeGroup&&map.hasLayer(edgeGroup));}topologyInspectionActive=active;if(active&&nodeLayer&&!map.hasLayer(nodeLayer))nodeLayer.addTo(map);else if(!active&&nodeLayer&&!topologyPreviousNodeVisibility&&map.hasLayer(nodeLayer))map.removeLayer(nodeLayer);if(currentState)renderEdges(currentState);if(active&&edgeGroup&&!map.hasLayer(edgeGroup))edgeGroup.addTo(map);else if(!active&&edgeGroup&&!topologyPreviousEdgeVisibility&&map.hasLayer(edgeGroup))map.removeLayer(edgeGroup);}
function openDetails(propertyPopup=false){if(!propertyPopup)details.classList.remove("property-popup");const returnToTopology=shouldSwapTopologyPanel()&&!topologyPanel.classList.contains("hidden");if(returnToTopology){narrowDetailsReturnToTopology=true;topologyPanel.classList.add("hidden");setTopologyInspection(false);}topologyBack.classList.toggle("hidden",!narrowDetailsReturnToTopology);details.classList.remove("hidden");refreshMapLayout();}
function closeDetails() { selectedNodeKey=null;activeOperationRevision=null;narrowDetailsReturnToTopology=false;details.classList.add("hidden");topologyBack.classList.add("hidden");clearPreview();clearEndpointHighlight();clearSelection();refreshMapLayout(); }
function returnToTopology(){narrowDetailsReturnToTopology=false;details.classList.add("hidden");topologyBack.classList.add("hidden");topologyPanel.classList.remove("hidden");document.querySelector("#topology-toggle").classList.add("active");setTopologyInspection(true);refreshMapLayout();}
let propertyTarget=null, propertyAnchor=null;
const propertyFields=['aeroway','name','ref'];
let propertyView=null;
function positionPropertyPopup(){
 if(!propertyAnchor||!details.classList.contains('property-popup')||details.classList.contains('hidden'))return;
 const point=map.latLngToContainerPoint(propertyAnchor),size=map.getSize(),width=300,height=300,gap=24;
 if(!size.x||!size.y)return;
 const position=popupPosition(point,size,{width,height,gap});
 details.style.left=position.x+'px';details.style.top=position.y+'px';
}
map.on('move zoom resize',positionPropertyPopup);
function showProperties(title, properties) {
 propertyView={title,properties};
 const canEdit=Boolean(currentState?.capabilities?.can_edit_graph&&document.body.classList.contains('graph-editing'));
 const ignored=new Set(['id','u_id','v_id','editable_attributes','validation_color',...propertyFields]);
 const inputs=propertyFields.map(key=>{
 const value=properties[key]??properties.editable_attributes?.[key]??'';
 if(key==='aeroway'){
 const types=['taxiway','runway','parking_position'];
 const options=[...(!types.includes(value)?[value]:[]),...types].map(type=>`<option value="${escapeHtml(type)}" ${type===value?'selected':''} ${!types.includes(type)?'disabled':''}>${escapeHtml(type||'未设置')}</option>`).join('');
 return `<label>${key}<select data-property="${key}" ${canEdit?'':'disabled'}>${options}</select></label>`;
 }
 return `<label>${key}<input data-property="${key}" value="${escapeHtml(value)}" ${canEdit?'':'readonly'}></label>`;
 }).join('');
 const rows=Object.entries(properties).filter(([key])=>!ignored.has(key)).map(([key,value])=>`<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(typeof value==='object'?JSON.stringify(value):value)}</dd>`).join('');
 detailsContent.innerHTML=`<h2>${escapeHtml(title)}</h2><div class="property-primary">${inputs}</div>${canEdit?'<button class="primary-button" id="save-properties">保存属性</button>':''}<dl>${rows}</dl>`;
 details.classList.add('property-popup');openDetails(true);positionPropertyPopup();
 if(canEdit){const revision=currentState.revision,target=propertyTarget;document.querySelector('#save-properties').onclick=async()=>{
 if(!document.body.classList.contains('graph-editing')||!currentState?.capabilities?.can_edit_graph){setStatus('请先进入编辑图');return}
 const values={};detailsContent.querySelectorAll('[data-property]').forEach(input=>values[input.dataset.property]=input.value);
 let attributes;try{attributes={...properties.editable_attributes,...propertyPatch(values)};requireRevision(revision)}catch(error){setStatus(error.message);return}
 const payload={attributes,expected_revision:revision,...(target.kind==='edge'?{edge:target.id}:{node:target.id})};
 try{await post(target.kind==='edge'?'/api/update-edge':'/api/update-node',payload,true);closeDetails();setStatus('属性已保存')}catch(error){setStatus(error.message)}
 };}
}
function showNodeProperties(feature){showProperties(`节点 ${feature.properties.node_id}`,feature.properties)}
function showConfirmation(title, html, confirmText, onConfirm, revision) {
  details.classList.remove("property-popup");
  activeOperationRevision=revision;
  detailsContent.innerHTML = `<h2>${escapeHtml(title)}</h2>${html}<div class="attribute-actions"><button id="cancel-action" class="secondary-button">取消</button><button id="confirm-action" class="primary-button">${escapeHtml(confirmText)}</button></div>`;
  openDetails();
  document.querySelector("#cancel-action").onclick = closeDetails;
  document.querySelector("#confirm-action").onclick = onConfirm;
}
function showGeometry(geometry, color = "#2563eb") { clearPreview(); previewLayer = L.geoJSON({type:"Feature", geometry}, {pane:"previewPane", interactive:false, style:{color,weight:4,opacity:.9,lineCap:"round",lineJoin:"round"}}).addTo(map); }
function highlightEdgeEndpoints(feature) {
  clearEndpointHighlight();
  const markers=[feature.properties.u_id,feature.properties.v_id].map(identifier=>nodeFeatureIndex.get(nodeKey(identifier))).filter(Boolean).map(node=>{
    const [longitude,latitude]=node.geometry.coordinates;
    return L.circleMarker([latitude,longitude],{pane:"selectionPane",radius:5,color:"#fff",weight:2,fillColor:"#2563eb",fillOpacity:1,interactive:false});
  });
  endpointLayer=L.layerGroup(markers).addTo(map);
}
function selectEdge(feature, fit = false, anchor = null) {
  propertyTarget={kind:"edge",id:feature.properties.id,feature};
  const coordinates=feature.geometry.coordinates.map(c=>L.latLng(c[1],c[0]));let total=0;const lengths=coordinates.slice(1).map((c,i)=>{const length=map.distance(coordinates[i],c);total+=length;return length});let remaining=total/2;let midpoint=coordinates[0];for(let i=0;i<lengths.length;i++){if(remaining<=lengths[i]){const t=lengths[i]?remaining/lengths[i]:0;midpoint=L.latLng(coordinates[i].lat+(coordinates[i+1].lat-coordinates[i].lat)*t,coordinates[i].lng+(coordinates[i+1].lng-coordinates[i].lng)*t);break}remaining-=lengths[i]}propertyAnchor=anchor||midpoint;
  selectedNodeKey=null;
  clearSelection(); highlightEdgeEndpoints(feature);
  selectionLayer=L.geoJSON({type:"Feature",geometry:feature.geometry},{pane:"selectionEdgePane",interactive:false,style:{color:"#2563eb",weight:4,opacity:1,lineCap:"round",lineJoin:"round"}}).addTo(map);
  if(fit) map.fitBounds(selectionLayer.getBounds(),{padding:[80,80],maxZoom:24});
  showProperties(`派生边 ${feature.properties.edge_id}`,feature.properties);
}
function selectNode(feature, fit = false) {
 propertyTarget={kind:"node",id:feature.properties.id};propertyAnchor=L.latLng(feature.geometry.coordinates[1],feature.geometry.coordinates[0]);
  clearSelection(); clearEndpointHighlight();
  const id=nodeKey(feature);selectedNodeKey=id;
  const incident=currentState.edges.features.filter(edge=>nodeKey(edge.properties.u_id)===id||nodeKey(edge.properties.v_id)===id);
  const neighbours=new Set(incident.map(edge=>nodeKey(edge.properties.u_id)===id?nodeKey(edge.properties.v_id):nodeKey(edge.properties.u_id)));
  const layersToShow=[];
  const seenGeometry=new Set();
  incident.forEach(edge=>{const geometryKey=JSON.stringify(edge.geometry);if(seenGeometry.has(geometryKey))return;seenGeometry.add(geometryKey);layersToShow.push(L.geoJSON({type:"Feature",geometry:edge.geometry},{pane:"selectionEdgePane",interactive:false,style:{color:"#2563eb",weight:3,opacity:.75,lineCap:"round",lineJoin:"round"}}));});
  neighbours.forEach(neighbour=>{const item=nodeFeatureIndex.get(neighbour);if(item){const [x,y]=item.geometry.coordinates;layersToShow.push(L.circleMarker([y,x],{pane:"selectionPane",radius:4,color:"#fff",fillColor:"#6683a5",fillOpacity:1,weight:1.5,interactive:false}));}});
  const [x,y]=feature.geometry.coordinates;
  layersToShow.push(L.circleMarker([y,x],{pane:"selectionPane",radius:8,color:"#fff",fillColor:"#2563eb",fillOpacity:1,opacity:1,weight:2.5,interactive:false}));
  selectionLayer=L.layerGroup(layersToShow).addTo(map);
  if(fit) map.setView([y,x],Math.max(map.getZoom(),22));
  showNodeProperties(feature);
}
function highlightMergeNodes(nodes) {
  clearSelection();
  const markers=nodes.map((node,index)=>{const [x,y]=node.position;return L.circleMarker([y,x],{pane:"selectionPane",radius:index===0?8:6,color:"#fff",fillColor:index===0?"#2563eb":"#6485ad",fillOpacity:1,weight:2,interactive:false});});
  selectionLayer=L.layerGroup(markers).addTo(map);
  if(markers.length) map.fitBounds(L.featureGroup(markers).getBounds(),{padding:[100,100],maxZoom:26});
}

let drawing = null;
function cancelDrawing(){drawing=null;clearPreview();closeDetails();}
function renderDrawing(){
  if(!drawing)return;
  const coordinates=[drawing.start.geometry.coordinates,...drawing.points];
  if(drawing.end)coordinates.push(drawing.end.geometry.coordinates);
  if(coordinates.length>1)showGeometry({type:"LineString",coordinates});else clearPreview();
  detailsContent.innerHTML=`<h2>直接绘制连接</h2><p>已添加 ${drawing.points.length} 个形状点。${drawing.end?"检查线路后确认添加。":"点击地图添加形状点，点击节点选择终点。"}</p><label>类型 <select id="draw-type"><option value="taxiway">滑行道</option><option value="runway">跑道</option><option value="parking_position">机位线</option></select></label><label>编号 <input id="draw-ref" placeholder="可选"></label><p>中间形状点及沿途交叉不会自动连接其他线路。</p><button id="draw-back">撤回最后一点</button><button id="draw-cancel">取消绘制</button><button id="draw-confirm" ${drawing.end?"":"disabled"}>确认添加</button>`;
  openDetails();
  document.querySelector("#draw-back").onclick=()=>{if(drawing.end)drawing.end=null;else drawing.points.pop();renderDrawing();};
  document.querySelector("#draw-cancel").onclick=cancelDrawing;
  document.querySelector("#draw-confirm").onclick=async()=>{
    const request={start:drawing.start.properties.id,end:drawing.end.properties.id,intermediate_points:drawing.points,expected_revision:drawing.revision,aeroway:document.querySelector("#draw-type").value,ref:document.querySelector("#draw-ref").value||null};
    document.querySelector("#draw-confirm").disabled=true;
    try{const result=await post("/api/draw-connection",request,true);cancelDrawing();setStatus(result.message);}
    catch(error){cancelDrawing();setStatus(`补线失败：${error.message}，请重新绘制`);}
  };
}
map.on("click",event=>{if(mode!=="draw"||!drawing||drawing.end)return;drawing.points.push([event.latlng.lng,event.latlng.lat]);renderDrawing();});
function drawingNodeClicked(feature){
  if(!currentState.capabilities?.can_edit_graph)return;
  if(!drawing)drawing={start:feature,points:[],end:null,revision:currentState.revision};
  else if(nodeKey(drawing.start)===nodeKey(feature))return setStatus("两个端点不能相同");
  else drawing.end=feature;
  renderDrawing();
}

async function previewRestore(start, end, expectedRevision) {
  try {
    const result = await post("/api/restore-options", {start,end,expected_revision:expectedRevision});
    if (!result.candidates.length) { firstNode = null; return setStatus("原始 OSM 来源网络中没有可靠的短路径候选"); }
    const options = result.candidates.map((candidate,index) => `<label class="source-option"><input type="radio" name="source-choice" value="${index}" ${index===0?"checked":""}><span>${escapeHtml(candidate.source_ids.join(" + "))}<br>OSM way ${escapeHtml(candidate.osm_way_ids.join(" + "))} · ${candidate.length_m.toFixed(2)} m</span></label>`).join("");
    showGeometry(result.candidates[0].geometry);
    showConfirmation("从 OSM 恢复连接", `<p>端点：${escapeHtml(result.current_endpoints.join(" — "))}</p><div class="source-options">${options}</div><p class="field-note">geometry 将从完整 SourceEdge 恢复，不会画直线。</p>`, "恢复连接", async () => {
      const index = Number(document.querySelector('input[name="source-choice"]:checked').value); const candidate = result.candidates[index];
      closeDetails(); try { const response = await post("/api/restore-confirm", {start,end,candidate_id:candidate.candidate_id,expected_revision:result.revision}, true); setStatus(response.message); } catch(error) { setStatus(`恢复失败：${error.message}`); }
    },result.revision);
    document.querySelectorAll('input[name="source-choice"]').forEach(input => input.onchange = () => showGeometry(result.candidates[Number(input.value)].geometry));
  } catch(error) { setStatus(`无法恢复：${error.message}`); }
  firstNode = null;firstNodeRevision=null;
}

async function previewMerge(request) {
  try {
    const result=await post("/api/merge-nodes-preview",{...request,expected_revision:request.expected_revision??currentState.revision});
    highlightMergeNodes(result.nodes);
    const choices=result.nodes.map((node,index)=>`<label class="source-option"><input type="radio" name="merge-canonical" value="${index}" ${identityKey(node.id)===identityKey(result.canonical_node_id)?"checked":""}><span>${escapeHtml(node.node_id)} · ${node.manual?"人工图节点":"OSM 图节点"}，度 ${node.degree}<br>${escapeHtml(node.source_ids.join(" + ")||"无 OSM SourceEdge 归属")}</span></label>`).join("");
    const warnings=result.warnings.map(item=>`<p class="warning">${escapeHtml(item)}</p>`).join("");
    showConfirmation("合并节点预览",`<dl><dt>成员</dt><dd>${escapeHtml(result.nodes.map(node=>node.node_id).join(", "))}</dd><dt>最大距离</dt><dd>${result.max_distance_m.toFixed(3)} m</dd><dt>受影响边</dt><dd>${result.affected_edges.length}</dd><dt>原始来源</dt><dd>SourceEdge 不会修改</dd></dl><h3>选择规范节点</h3><div class="source-options">${choices}</div>${warnings}`,"确认合并",async()=>{
      const index=Number(document.querySelector('input[name="merge-canonical"]:checked').value);
      const body={node_ids:result.node_ids,canonical_node_id:result.nodes[index].id,expected_revision:result.revision};
      closeDetails();try{const response=await post("/api/merge-nodes-confirm",body,true);mergeNodeIds=[];setStatus(response.message);}catch(error){setStatus(`合并失败：${error.message}`);}
    },result.revision);
  } catch(error){setStatus(`无法合并：${error.message}`);}
}

async function openMergeCandidates() {
  try {
    const result=await readResponse(await fetch("/api/merge-candidates"));
    const rows=result.candidates.map((candidate,index)=>`<div class="merge-candidate"><strong>候选 ${index+1} · 最大距离 ${candidate.max_distance_m.toFixed(3)} m</strong><div class="candidate-nodes">${candidate.nodes.map((node,nodeIndex)=>`<button class="candidate-node secondary-button" data-candidate="${index}" data-node="${nodeIndex}">${escapeHtml(node.node_id)}</button>`).join("")}</div><button class="candidate-use primary-button" data-candidate="${index}">检查并合并</button></div>`).join("");
    detailsContent.innerHTML=`<h2>疑似重复图节点</h2><p class="field-note">候选距离 ≤ 0.5 m</p><div class="source-options">${rows||"<p>没有 0.5 米内的候选组</p>"}</div>`;openDetails();
    document.querySelectorAll(".candidate-node").forEach(button=>button.onclick=()=>{const candidate=result.candidates[Number(button.dataset.candidate)];const node=candidate.nodes[Number(button.dataset.node)];highlightMergeNodes(candidate.nodes);map.setView([node.position[1],node.position[0]],Math.max(map.getZoom(),24));setStatus(`候选来源节点 ${node.node_id}`);});
    document.querySelectorAll(".candidate-use").forEach(button=>button.onclick=()=>previewMerge({node_ids:result.candidates[Number(button.dataset.candidate)].node_ids,expected_revision:result.revision}));
  }catch(error){setStatus(`无法读取合并候选：${error.message}`);}
}

function showManualMergeSelection() {
  const selected=mergeNodeIds.map(id=>nodeFeatureIndex.get(nodeKey(id))).filter(Boolean);
  highlightMergeNodes(selected.map(feature=>({position:feature.geometry.coordinates})));
  detailsContent.innerHTML=`<h2>手工合并节点</h2><p>已选择 ${selected.length} 个节点</p><div class="source-options">${selected.map(feature=>`<div class="source-choice">${escapeHtml(feature.properties.node_id)}</div>`).join("")}</div><div class="attribute-actions"><button id="clear-merge" class="secondary-button">清空选择</button><button id="preview-merge" class="primary-button" ${selected.length<2?"disabled":""}>停止选择并检查</button></div>`;openDetails();
  document.querySelector("#clear-merge").onclick=()=>{mergeNodeIds=[];mergeSelectionRevision=null;openMergeCandidates();clearSelection();};
  document.querySelector("#preview-merge").onclick=()=>previewMerge({node_ids:mergeNodeIds,expected_revision:mergeSelectionRevision});
}

async function previewEdgeDeletion(edge) {
  try { const result = await post("/api/delete-edge-preview", {edge,expected_revision:currentState.revision}); const sources=result.source_segments.map(segment=>`${escapeHtml(segment.source_id)} [${segment.source_start_m.toFixed(2)}, ${segment.source_end_m.toFixed(2)}]${segment.reversed?" 反向":""}`).join("<br>"); showConfirmation("删除派生边", `<dl><dt>边</dt><dd>${escapeHtml(result.edge)}</dd><dt>来源片段</dt><dd>${sources||"无"}</dd><dt>原始数据</dt><dd>SourceEdge 不会被删除</dd></dl>`, "删除派生边", async () => { closeDetails(); try { const response = await post("/api/delete-edge-confirm", {edge,expected_revision:result.revision}, true); setStatus(response.message); } catch(error) { setStatus(`删除失败：${error.message}`); } },result.revision); }
  catch(error) { setStatus(`无法删除：${error.message}`); }
}

async function previewNodeDeletion(node) {
  try {
    const result = await post("/api/delete-node-preview", {node,expected_revision:currentState.revision});
    const halves=result.half_edges.map(half=>`<div class="source-choice"><strong>${escapeHtml(half.half_id)} · 通向 ${escapeHtml(half.outer_node)}</strong><span>${escapeHtml(half.edge)}</span><span>${escapeHtml(half.source_ids.join(" + "))}</span></div>`).join("");
    const pairs=result.pair_candidates.map(pair=>`<label class="source-option pair-option" data-pair="${pair.pair_id}"><input type="checkbox" name="node-pair" value="${pair.pair_id}" ${pair.recommended?"checked":""}><span><strong>${escapeHtml(pair.endpoints.join(" ↔ "))}</strong><br>${escapeHtml(pair.source_ids.join(" + "))}<br>转角 ${pair.angle_degrees}°${pair.same_source?" · 同源":" · 跨来源"}</span></label>`).join("");
    const unpaired=result.recommended_unpaired.length?`<p class="warning">推荐方案仍有未配对半边：${escapeHtml(result.recommended_unpaired.join(", "))}</p>`:"";
    showConfirmation("删除节点并重组连接", `<p>节点 ${escapeHtml(result.node)} · ${result.half_edges.length} 条关联半边</p><h3>关联半边</h3><div class="source-options">${halves||"<p>无关联边</p>"}</div><h3>选择半边配对</h3><div class="source-options">${pairs||"<p>没有可配对的半边</p>"}</div><p id="pair-stats" class="field-note"></p>${unpaired}<label class="source-option"><input id="discard-unpaired" type="checkbox"><span>明确删除所有未配对半边（可能改变拓扑）</span></label><p class="field-note">同一条半边可以参加多组连接。新边会从有序 SourceSegment 链重建，不会画直线；原始 SourceEdge 不会修改。</p>`, "执行人工重组", async () => {
      const pair_ids=[...document.querySelectorAll('input[name="node-pair"]:checked')].map(input=>input.value); const discard_unpaired=document.querySelector("#discard-unpaired").checked;
      closeDetails(); try { const response=await post("/api/delete-node-confirm", {node,pair_ids,discard_unpaired,expected_revision:result.revision}, true); setStatus(response.message); } catch(error) { setStatus(`删除失败：${error.message}`); }
    },result.revision);
    const updatePairStats=()=>{const checked=[...document.querySelectorAll('input[name="node-pair"]:checked')];const used=new Set();checked.forEach(input=>{const pair=result.pair_candidates.find(item=>item.pair_id===input.value);used.add(pair.left);used.add(pair.right);});const missing=result.half_edges.filter(half=>!used.has(half.half_id)).map(half=>half.half_id);document.querySelector("#pair-stats").textContent=`已选择 ${checked.length} 组连接 · 已使用 ${used.size}/${result.half_edges.length} 条半边${missing.length?` · 未使用：${missing.join(", ")}`:" · 无未使用半边"}`;};
    document.querySelectorAll(".pair-option").forEach(label=>{label.onmouseenter=()=>{const pair=result.pair_candidates.find(item=>item.pair_id===label.dataset.pair);showGeometry(pair.geometry,"#db2777");};label.querySelector("input").onchange=updatePairStats;});updatePairStats();
  } catch(error) { setStatus(`无法删除：${error.message}`); }
}

async function previewSplit(edge, latlng) {
  const body={edge,longitude:latlng.lng,latitude:latlng.lat,expected_revision:currentState.revision};
  try {
    const result=await post("/api/split-source-preview",body);
    const choices=result.candidates.map((candidate,index)=>`<label class="source-option"><input type="radio" name="split-node" value="${index}" ${index===0?"checked":""}><span>OSM Node ${escapeHtml(candidate.id.value)} · 距离 ${candidate.distance_m.toFixed(2)} m</span></label>`).join("");
    const manual=result.candidates.length?"":`<label class="source-option"><input type="radio" name="split-node" value="" checked><span>没有合适 OSM Node，创建负数 ID 人工节点</span></label>`;
    showConfirmation("补充图分割点", `<p class="field-note">在当前派生边中加入一个拓扑节点，并把该边按原始 SourceEdge 曲线切成两段；原始曲线本身不会改变。</p><dl><dt>命中来源</dt><dd>${escapeHtml(result.source_id)}</dd></dl><div class="source-options">${choices}${manual}</div>`, "确认切分", async()=>{
      const selected=document.querySelector('input[name="split-node"]:checked'); const request={...body,osm_node_id:selected.value===""?null:result.candidates[Number(selected.value)].id,expected_revision:result.revision};
      closeDetails(); try { const response=await post("/api/split-source-confirm",request,true); setStatus(response.message); } catch(error){setStatus(`切分失败：${error.message}`);}
    },result.revision);
  } catch(error){setStatus(`无法切分：${error.message}`);}
}

async function previewManualSnap(node, edge, expectedRevision) {
  try {
    const result=await post("/api/manual-snap-preview",{node,edge,expected_revision:expectedRevision});
    showGeometry(result.connector_geometry,"#db2777");
    showConfirmation("人工吸附预览",`<dl><dt>节点</dt><dd>${escapeHtml(result.node)}</dd><dt>目标边</dt><dd>${escapeHtml(result.edge)}</dd><dt>移动距离</dt><dd>${result.distance_m.toFixed(3)} m</dd><dt>目标来源</dt><dd>${escapeHtml(result.target_source_id)}</dd><dt>来源位置</dt><dd>${result.target_station_m.toFixed(3)} m</dd><dt>原始数据</dt><dd>SourceEdge 不会修改</dd></dl><p class="field-note">确认后会移动图节点、重建它原有的关联边，并在目标来源区间切分派生边。</p>`,"确认人工吸附",async()=>{
      closeDetails();try{const response=await post("/api/manual-snap-confirm",{node,edge,expected_revision:result.revision},true);firstNode=null;firstNodeRevision=null;setStatus(response.message);}catch(error){setStatus(`人工吸附失败：${error.message}`);}
    },result.revision);
  }catch(error){firstNode=null;firstNodeRevision=null;setStatus(`无法人工吸附：${error.message}`);}
}

function nodeClicked(feature,event) {
  L.DomEvent.stopPropagation(event); const p=feature.properties;
  if(mode==="draw")return drawingNodeClicked(feature);
  selectNode(feature);
  if(mode==="delete") return previewNodeDeletion(p.id);
  if(mode==="restore") { if(!firstNode){firstNode=p.id;firstNodeRevision=currentState.revision;event.target.setStyle({radius:6,color:"#2563eb",weight:2});return setStatus(`已选择 ${p.node_id}，请选择另一个 OSM 图节点`);} if(nodeKey(firstNode)===nodeKey(p.id))return setStatus("两个端点不能相同"); return previewRestore(firstNode,p.id,firstNodeRevision); }
  if(mode==="snap") { firstNode=p.id;firstNodeRevision=currentState.revision;return setStatus(`已选择节点 ${p.node_id}，请点击需要接入的目标派生边`); }
  if(mode==="merge") { if(!mergeNodeIds.length)mergeSelectionRevision=currentState.revision;if(!mergeNodeIds.some(id=>nodeKey(id)===nodeKey(p.id)))mergeNodeIds.push(p.id);showManualMergeSelection();return setStatus(`已选择 ${mergeNodeIds.length} 个待合并节点`); }
}
function edgeClicked(feature,event) { L.DomEvent.stopPropagation(event); if(mode==="draw"){if(drawing&&!drawing.end){drawing.points.push([event.latlng.lng,event.latlng.lat]);renderDrawing();}return;} selectEdge(feature,false,event.latlng); const p=feature.properties; if(mode==="delete")return previewEdgeDeletion(p.id); if(mode==="split")return previewSplit(p.id,event.latlng);if(mode==="snap"){if(!firstNode)return setStatus("请先选择需要人工吸附的图节点");return previewManualSnap(firstNode,p.id,firstNodeRevision);} }

function renderNodes() {
  if(nodeLayer) { layers.removeLayer(nodeLayer); map.removeLayer(nodeLayer); }
  nodeLayer=L.geoJSON({type:"FeatureCollection",features:nodeFeatures},{pane:"nodesPane",pointToLayer:(feature,latlng)=>{const p=feature.properties;if(p.node_type==="runway_interface")return L.marker(latlng,{pane:"nodesPane",icon:L.divIcon({className:`business-node-icon ${p.node_type}`,html:"R",iconSize:[20,20]})});return L.circleMarker(latlng,{pane:"nodesPane",radius:Math.max(Number(p.radius)||0,4),color:"rgba(255,255,255,.9)",fillColor:p.color,fillOpacity:.9,weight:1.5});},onEachFeature:(feature,layer)=>layer.on("click",event=>nodeClicked(feature,event))});
  if(!currentState?.flight_mode||topologyInspectionActive)nodeLayer.addTo(map); layers.addOverlay(nodeLayer,`图节点 (${nodeFeatures.length})`);
}
function renderEdges(data) {
  const wasVisible=!edgeGroup||map.hasLayer(edgeGroup);
  if(edgeGroup){layers.removeLayer(edgeGroup);map.removeLayer(edgeGroup);}
  const flightMode=Boolean(data.flight_mode);
  const inspection=topologyInspectionActive||splitValidation;
  const casing=L.geoJSON(data.edges,{pane:"edgeCasingPane",interactive:false,style:{color:"rgba(255,255,255,.8)",weight:flightMode&&!inspection?4.5:5,opacity:flightMode&&!inspection?.58:.65}});
  edgeSearchIndex.clear();
  edgeIdentityIndex.clear();
  edgeLayer=L.geoJSON(data.edges,{pane:"edgesPane",style:feature=>({color:feature.properties.aeroway==="parking_position"?"#dc6b32":splitValidation?feature.properties.validation_color:flightMode&&!topologyInspectionActive?"#526875":"#9a684d",weight:splitValidation?3.4:flightMode&&!topologyInspectionActive?3:2.8,opacity:splitValidation?.95:flightMode&&!topologyInspectionActive?.78:.78}),onEachFeature:(feature,layer)=>{layer.on("click",event=>edgeClicked(feature,event));layer.on("mouseover",()=>layer.setStyle({weight:5,color:"#243746",opacity:1}));layer.on("mouseout",()=>edgeLayer.resetStyle(layer));const key=edgePairKey(feature.properties.u,feature.properties.v);if(!edgeSearchIndex.has(key))edgeSearchIndex.set(key,[]);edgeSearchIndex.get(key).push({feature,layer});edgeIdentityIndex.set(edgeKey(feature),{feature,layer});}});
  edgeGroup=L.layerGroup([casing,edgeLayer]);if(wasVisible)edgeGroup.addTo(map);layers.addOverlay(edgeGroup,`派生边 (${data.edge_count})`);
}
function renderReferenceLayers(data) {

  dataLayers.forEach(layer => { layers.removeLayer(layer); map.removeLayer(layer); }); dataLayers=[];
  const flightColors=["#0066cc","#00a878","#7b2cbf","#e76f00","#008c9e","#c03664","#5c7c19","#5f4bb6"];
  const pathColors=["#d00040","#6a00a8","#005f73","#b23a00","#2b6f3e","#8f2d56","#3a0ca3","#9c5700"];
  const dashPatterns=[null,"12 6","3 5","16 5 3 5"];
  data.flights.forEach((collection,index)=>{const color=flightColors[index%flightColors.length];const layer=L.geoJSON(collection,{pane:"flightPane",interactive:false,style:{pane:"flightPane",color:"#fff",weight:7,opacity:.88},pointToLayer:(_feature,latlng)=>L.circleMarker(latlng,{pane:"flightPane",radius:2.5,color:"#fff",fillColor:color,weight:1,fillOpacity:.95})});const accent=L.geoJSON(collection,{pane:"flightPane",interactive:false,filter:feature=>feature.geometry.type!=="Point",style:{pane:"flightPane",color,weight:4.5,opacity:.96,dashArray:dashPatterns[Math.floor(index/flightColors.length)%dashPatterns.length]}});const group=L.layerGroup([layer,accent]);dataLayers.push(group);layers.addOverlay(group,`Flight ${index+1}`);group.addTo(map);});
  data.paths.forEach((collection,index)=>{const color=pathColors[index%pathColors.length];const casing=L.geoJSON(collection,{pane:"pathPane",interactive:false,style:{pane:"pathPane",color:"#fff",weight:9,opacity:.92}});const accent=L.geoJSON(collection,{pane:"pathPane",interactive:false,style:{pane:"pathPane",color,weight:6,opacity:.98,dashArray:dashPatterns[Math.floor(index/pathColors.length)%dashPatterns.length]}});const group=L.layerGroup([casing,accent]);dataLayers.push(group);layers.addOverlay(group,`Path ${index+1}`);group.addTo(map);});
}
function updateNodeReviewControls(){const active=nodeReviewIndex>=0&&nodeReviewSnapshot.length>0;document.querySelector("#node-review-start").disabled=!nodeFeatures.length||!currentState?.capabilities?.can_edit_graph;document.querySelector("#node-review-prev").disabled=!active||nodeReviewIndex===0;document.querySelector("#node-review-next").disabled=!active||nodeReviewIndex===nodeReviewSnapshot.length-1;document.querySelector("#node-review-end").disabled=!active;document.querySelector("#node-review-progress").textContent=active?`遍历位置 ${nodeReviewIndex+1} / ${nodeReviewSnapshot.length} · 节点 ${nodeReviewSnapshot[nodeReviewIndex].properties.node_id}`:"尚未开始";}
function endNodeReview(message=""){nodeReviewSnapshot=[];nodeReviewIndex=-1;updateNodeReviewControls();if(message)setStatus(message);}
function showNodeReviewPosition(fit=true){const feature=nodeReviewSnapshot[nodeReviewIndex];if(!feature)return endNodeReview("节点快照已失效，请重新开始逐点检查");if(nodeLayer&&!map.hasLayer(nodeLayer))nodeLayer.addTo(map);selectNode(feature,fit);updateNodeReviewControls();if(nodeReviewIndex===nodeReviewSnapshot.length-1)setStatus("已到最后一个节点；这不表示全部复核通过");}
function startNodeReview(){if(!nodeFeatures.length)return setStatus("当前图没有可检查节点");nodeReviewSnapshot=sortedNodeReviewSnapshot(nodeFeatures);nodeReviewIndex=0;showNodeReviewPosition(true);}
function moveNodeReview(delta){if(nodeReviewIndex<0)return;const target=nodeReviewIndex+delta;if(target<0||target>=nodeReviewSnapshot.length)return;nodeReviewIndex=target;showNodeReviewPosition(true);}
async function loadState(){const data=await readResponse(await fetch("/api/state"));if(lifecycle.disposed)return;const topologyChanged=lastTopologyRevision!==null&&lastTopologyRevision!==data.topology_revision;if(nodeReviewIndex>=0&&(topologyChanged||!data.capabilities?.can_edit_graph))endNodeReview(topologyChanged?"拓扑已变更，逐点检查已结束，请重新开始":"已离开编辑模式，逐点检查已结束");lastTopologyRevision=data.topology_revision;currentState=data;window.dispatchEvent(new CustomEvent("workbench-state",{detail:data}));document.body.classList.add("flight-mode","unified-workbench");document.title="Airport Workbench";document.querySelector(".brand-copy strong").textContent="Airport Workbench";renderEdges(data);nodeFeatures=data.nodes.features;nodeFeatureIndex.clear();nodeSearchIndex.clear();nodeFeatures.forEach(feature=>{nodeFeatureIndex.set(nodeKey(feature),feature);const searchKey=normalizeId(feature.properties.node_id);if(!nodeSearchIndex.has(searchKey))nodeSearchIndex.set(searchKey,[]);nodeSearchIndex.get(searchKey).push(feature);});if(nodeReviewIndex>=0)nodeReviewSnapshot=nodeReviewSnapshot.map(feature=>nodeFeatureIndex.get(nodeKey(feature))).filter(Boolean);renderNodes();renderReferenceLayers(data);renderTopologySummary(data.topology);updateNodeReviewControls();if(selectedNodeKey){const selected=nodeFeatureIndex.get(selectedNodeKey);if(selected)selectNode(selected);else closeDetails();}document.querySelector("#counts").textContent=`${data.node_count} 节点 · ${data.edge_count} 边 · ${data.flight_count} 航班`;savePath=data.save_path;document.querySelector("#undo").disabled=!data.can_undo;document.querySelector("#finish").classList.toggle("hidden",!data.can_finish);if(data.flight_mode)setStatus("航班模式 · 待匹配可批量选择，地图最多展示 10 条");if(!fitted){if(nodeLayer&&map.hasLayer(nodeLayer))map.removeLayer(nodeLayer);const nodeBounds=nodeLayer.getBounds(),edgeBounds=edgeLayer.getBounds();if(nodeBounds.isValid()){map.fitBounds(nodeBounds,{padding:[24,24]});fitted=true;}else if(edgeBounds.isValid()){map.fitBounds(edgeBounds,{padding:[24,24]});fitted=true;}}validateOperationRevisions();lifecycle.timeout(()=>map.invalidateSize(),0);}
function validateOperationRevisions(){if(!currentState)return;const staleOperation=activeOperationRevision!==null&&activeOperationRevision!==currentState.revision;const staleSelection=(firstNodeRevision!==null&&firstNodeRevision!==currentState.revision)||(mergeSelectionRevision!==null&&mergeSelectionRevision!==currentState.revision);if(staleOperation||staleSelection){closeDetails();firstNode=null;firstNodeRevision=null;mergeNodeIds=[];mergeSelectionRevision=null;setStatus("图已变更，旧操作已失效，请重新检查");}};

function renderTopologySummary(topology) {
  const metrics = [
    [topology.component_count,"连通分量",topology.component_count>1,"components"],
    [topology.largest_component,"最大分量节点",false,"component-1"],
    [topology.dangling_count,"度为 1",topology.dangling_count>0,"dangling"],
    [topology.isolated_count,"度为 0",topology.isolated_count>0,"isolated"],
    [topology.parallel_pair_count,"平行边端点组",topology.parallel_pair_count>0,"parallel"]
  ];
  document.querySelector("#topology-summary").innerHTML = metrics.map(([value,label,alert,action])=>`<button class="metric actionable ${alert?"alert":""}" data-topology-action="${action}" ${value?"":"disabled"}><strong>${value}</strong><span>${label}</span></button>`).join("");
  const componentRows=topology.components.map(item=>`<button class="topology-item" data-component="${item.index}"><span>分量 ${item.index}</span><small>${item.size} 个节点</small></button>`).join("");
  const parallelRows=topology.parallel_groups.map((item,index)=>`<button class="topology-item" data-parallel="${index}"><span>${escapeHtml(item.u)} ↔ ${escapeHtml(item.v)}</span><small>${item.edge_ids.length} 条边</small></button>`).join("");
  document.querySelector("#topology-details").innerHTML=`<section class="topology-section"><h3>连通分量</h3><div class="topology-list">${componentRows||'<p class="topology-empty">无节点</p>'}</div></section><section class="topology-section"><h3>平行边</h3><div class="topology-list">${parallelRows||'<p class="topology-empty">未发现平行边</p>'}</div></section>`;
  const showNodes=(features,label)=>{clearSelection();if(!features.length)return setStatus(`${label}中没有节点`);const markers=features.map(feature=>{const [x,y]=feature.geometry.coordinates;return L.circleMarker([y,x],{pane:"selectionPane",radius:7,color:"#fff",fillColor:"#a34f6a",fillOpacity:.9,weight:2,interactive:false});});selectionLayer=L.layerGroup(markers).addTo(map);map.fitBounds(L.featureGroup(markers).getBounds(),{padding:[80,80],maxZoom:22});setStatus(`${label} · ${features.length} 个节点`);};
  const showComponent=index=>{const item=topology.components.find(component=>component.index===index);if(item){const ids=new Set(item.node_ids.map(nodeKey));showNodes(nodeFeatures.filter(feature=>ids.has(nodeKey(feature))),`连通分量 ${index}`);}};
  const showParallel=index=>{const item=topology.parallel_groups[index];if(!item)return;clearSelection();clearEndpointHighlight();const features=item.edge_ids.map(id=>edgeIdentityIndex.get(edgeKey(id))?.feature).filter(Boolean);selectionLayer=L.geoJSON({type:"FeatureCollection",features},{pane:"selectionEdgePane",interactive:false,style:{color:"#765f7f",weight:8,opacity:.9}}).addTo(map);map.fitBounds(selectionLayer.getBounds(),{padding:[80,80],maxZoom:24});setStatus(`平行边 ${item.u} ↔ ${item.v} · ${features.length} 条`);};
  document.querySelectorAll("[data-component]").forEach(button=>button.onclick=()=>showComponent(Number(button.dataset.component)));
  document.querySelectorAll("[data-parallel]").forEach(button=>button.onclick=()=>showParallel(Number(button.dataset.parallel)));
  document.querySelectorAll("[data-topology-action]").forEach(button=>button.onclick=()=>{const action=button.dataset.topologyAction;if(action==="component-1")showComponent(1);else if(action==="components")showNodes(nodeFeatures,"全部连通分量");else if(action==="isolated")showNodes(nodeFeatures.filter(feature=>feature.properties.degree===0),"度为 0 的节点");else if(action==="dangling")showNodes(nodeFeatures.filter(feature=>feature.properties.degree===1),"度为 1 的节点");else if(action==="parallel"&&topology.parallel_groups.length)showParallel(0);});
}

function setEditorTool(nextMode){
 if(!Object.hasOwn(messages,nextMode))return;
 if(nextMode!=='inspect'&&(!currentState?.capabilities?.can_edit_graph||!document.body.classList.contains('graph-editing')))return;
 document.querySelectorAll('.tool').forEach(item=>item.classList.toggle('active',item.dataset.mode===nextMode));
 cancelDrawing();mode=nextMode;firstNode=null;firstNodeRevision=null;mergeNodeIds=[];mergeSelectionRevision=null;closeDetails();setStatus(messages[mode]);if(mode==='merge')openMergeCandidates();publishMapState();
}
document.querySelectorAll('.tool').forEach(button=>button.onclick=()=>setEditorTool(button.dataset.mode));
document.querySelector("#close-details").onclick=closeDetails;
topologyBack.onclick=returnToTopology;
document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>{document.querySelector(`#${button.dataset.close}`).classList.add("hidden");if(button.dataset.close==="topology-panel"){document.querySelector("#topology-toggle").classList.remove("active");setTopologyInspection(false);}refreshMapLayout();});
document.querySelector("#split-validation-toggle").onclick=event=>{splitValidation=!splitValidation;event.currentTarget.classList.toggle("active",splitValidation);event.currentTarget.textContent=splitValidation?"关闭相邻边辨色":"开启相邻边辨色";document.querySelector(".legend").classList.toggle("validation",splitValidation);if(currentState)renderEdges(currentState);setStatus(splitValidation?"拓扑辨色已开启 · 相邻边使用不同颜色，便于检查连接关系":"拓扑辨色已关闭 · 派生边恢复统一颜色");};
document.querySelector("#node-review-start").onclick=startNodeReview;
document.querySelector("#node-review-prev").onclick=()=>moveNodeReview(-1);
document.querySelector("#node-review-next").onclick=()=>moveNodeReview(1);
document.querySelector("#node-review-end").onclick=()=>endNodeReview("逐点检查已结束；当前节点保持选中");
document.querySelector("#search-node-button").onclick=()=>{const matches=nodeSearchIndex.get(normalizeId(document.querySelector("#search-node").value))||[];if(!matches.length)return setStatus("未找到该节点");if(matches.length>1)return setStatus("节点 ID 文本存在多种类型，请在地图上选择目标节点");selectNode(matches[0],true);setStatus(`已选中节点 ${matches[0].properties.node_id}`);};
document.querySelector("#search-edge-button").onclick=()=>{const entries=edgeSearchIndex.get(edgePairKey(document.querySelector("#search-edge-u").value,document.querySelector("#search-edge-v").value));if(!entries?.length)return setStatus("未找到该组端点的派生边");selectEdge(entries[0].feature,true);setStatus(`已选中派生边；该组端点共有 ${entries.length} 条边`);};
async function saveGraph(){try{const response=await post("/api/save",{expected_revision:currentState.revision},true);setStatus(response.message);}catch(error){setStatus(`保存失败：${error.message}`);}};
async function undoGraph(){try{const response=await post("/api/undo",{expected_revision:currentState.revision},true);setStatus(response.message);}catch(error){setStatus(`撤销失败：${error.message}`);}};
async function finishGraph(){try{const result=await post("/api/finish",{expected_revision:currentState.revision});setStatus(result.message);}catch(error){setStatus(`完成失败：${error.message}`);}};
lifecycle.listen(document,"pointerdown",()=>{conflictNotice=false;},{capture:true});
lifecycle.listen(document,"keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z"){if(event.target?.closest?.("input,textarea,select,[contenteditable=true]"))return;event.preventDefault();if(currentState?.can_undo&&currentState?.capabilities?.can_edit_graph&&document.body.classList.contains('graph-editing'))undoGraph();}});
lifecycle.observe(document.querySelector(".workspace"),refreshMapLayout);
loadState().catch(error=>setStatus(`载入失败：${error.message}`));

document.querySelector('#map-view').append(details);
const standSearch=document.createElement('label');standSearch.innerHTML='机位编号 ref<div class="input-action"><input id="search-stand-ref" placeholder="机位编号"><button id="search-stand-button">搜索</button></div><div id="stand-search-results"></div>';document.querySelector('#search-panel').append(standSearch);document.querySelector('#search-panel .panel-heading small')?.remove();
document.querySelector('#search-stand-button').onclick=()=>{const ref=document.querySelector('#search-stand-ref').value.trim();const matches=currentState.edges.features.filter(f=>f.properties.aeroway==='parking_position'&&String(f.properties.ref??'')===ref);const results=document.querySelector('#stand-search-results');results.replaceChildren();if(!matches.length){results.textContent='未找到机位边';return}if(matches.length===1){document.querySelector("#search-panel").classList.add("hidden");selectEdge(matches[0],true);return}matches.forEach(f=>{const button=document.createElement('button');button.textContent=String(f.properties.edge_id);button.onclick=()=>{document.querySelector("#search-panel").classList.add("hidden");selectEdge(f,true)};results.append(button)})};

lifecycle.listen(window,'graph-editing-changed',()=>{
 mode='inspect';document.querySelectorAll('.tool').forEach(tool=>tool.classList.toggle('active',tool.dataset.mode==='inspect'));
 clearPreview();firstNode=null;mergeNodeIds=[];
 if(propertyView&&details.classList.contains('property-popup')&&!details.classList.contains('hidden'))showProperties(propertyView.title,propertyView.properties);
});

function publishMapState(){window.dispatchEvent(new Event('map-controller-changed'))}
function toggleMapSearch(){document.querySelector('#search-panel').classList.toggle('hidden');publishMapState()}
function toggleMapTopology(){const opening=topologyPanel.classList.contains('hidden');if(opening&&shouldSwapTopologyPanel()&&!details.classList.contains('hidden')){narrowDetailsReturnToTopology=false;details.classList.add('hidden');topologyBack.classList.add('hidden');}topologyPanel.classList.toggle('hidden');setTopologyInspection(opening);refreshMapLayout();publishMapState()}
window.workbenchMap={
 snapshot:()=>({ready:Boolean(currentState),canEdit:Boolean(currentState?.capabilities?.can_edit_graph),editing:document.body.classList.contains('graph-editing'),canUndo:Boolean(currentState?.can_undo),canFinish:Boolean(currentState?.can_finish),mode,nodeCount:currentState?.node_count??0,edgeCount:currentState?.edge_count??0,flightCount:currentState?.flight_count??0}),
 setTool:setEditorTool,save:saveGraph,undo:undoGraph,finish:finishGraph,search:toggleMapSearch,topology:toggleMapTopology,
 toggleEditing:()=>{if(!currentState?.capabilities?.can_edit_graph)return;document.body.classList.toggle('graph-editing');window.dispatchEvent(new Event('graph-editing-changed'));window.dispatchEvent(new Event('resize'));publishMapState()},
};
lifecycle.listen(window,'workbench-state',()=>lifecycle.frame(publishMapState));
document.querySelector('#save').onclick=saveGraph;document.querySelector('#undo').onclick=undoGraph;document.querySelector('#finish').onclick=finishGraph;

document.querySelector('#search-toggle').onclick=toggleMapSearch;
document.querySelector('#topology-toggle').onclick=toggleMapTopology;

export { map, layers, escapeHtml, readResponse, setStatus };

lifecycle.own(()=>map.remove());

lifecycle.own(()=>{delete window.workbenchMap;});
